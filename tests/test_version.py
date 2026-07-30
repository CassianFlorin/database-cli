"""Guards on the version the project reports.

Releases are tagged automatically from commit history, so nothing stops the
declared version from drifting away from the tag -- it had, by three releases.
The workflow now rewrites both files, and these tests keep that honest: one
checks the two files agree, the rest check the rewriter itself, which runs
unattended and would otherwise corrupt the manifest in silence.
"""

import importlib.machinery
import importlib.util
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_MANIFEST = ROOT / ".codex-plugin" / "plugin.json"
MCP_SERVER = ROOT / "skills" / "database-cli" / "scripts" / "database-mcp"
LANDING_PAGE = ROOT / "docs" / "index.html"


def load_setter():
    loader = importlib.machinery.SourceFileLoader(
        "set_version", str(ROOT / ".github" / "scripts" / "set_version.py")
    )
    spec = importlib.util.spec_from_loader("set_version", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def declared_page_version(path=LANDING_PAGE):
    match = re.search(r'<span class="badge v">v([^<]*)</span>', path.read_text(encoding="utf-8"))
    return match.group(1) if match else None


def declared_server_version(path=MCP_SERVER):
    match = re.search(r'^SERVER_VERSION = "([^"]*)"$', path.read_text(encoding="utf-8"), re.M)
    return match.group(1) if match else None


class VersionConsistencyTest(unittest.TestCase):
    def test_every_declared_version_agrees(self):
        manifest = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))["version"]

        self.assertEqual(manifest, declared_server_version())
        self.assertEqual(manifest, declared_page_version(), "landing page badge is stale")

    def test_declared_version_looks_like_a_release(self):
        manifest = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))["version"]

        self.assertRegex(manifest, r"\A\d+\.\d+\.\d+\Z")


class SetVersionTest(unittest.TestCase):
    def setUp(self):
        self.mod = load_setter()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for source in (PLUGIN_MANIFEST, MCP_SERVER, LANDING_PAGE):
            target = self.root / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    def manifest(self):
        return self.root / ".codex-plugin" / "plugin.json"

    def server(self):
        return self.root / "skills" / "database-cli" / "scripts" / "database-mcp"

    def page(self):
        return self.root / "docs" / "index.html"

    def test_writes_the_version_into_every_file(self):
        self.mod.set_version(self.root, "1.2.3")

        self.assertEqual(json.loads(self.manifest().read_text(encoding="utf-8"))["version"], "1.2.3")
        self.assertEqual(declared_server_version(self.server()), "1.2.3")
        self.assertEqual(declared_page_version(self.page()), "1.2.3")

    def test_page_badge_keeps_its_v_prefix_and_markup(self):
        self.mod.set_version(self.root, "2.0.0")

        self.assertIn('<span class="badge v">v2.0.0</span>', self.page().read_text(encoding="utf-8"))

    def test_manifest_stays_valid_json_and_keeps_its_other_fields(self):
        before = json.loads(self.manifest().read_text(encoding="utf-8"))
        self.mod.set_version(self.root, "9.9.9")
        after = json.loads(self.manifest().read_text(encoding="utf-8"))

        self.assertEqual(list(before), list(after), "key order must survive the edit")
        self.assertEqual({k: v for k, v in after.items() if k != "version"},
                         {k: v for k, v in before.items() if k != "version"})

    def test_mcp_server_still_parses(self):
        self.mod.set_version(self.root, "1.2.3")
        compile(self.server().read_text(encoding="utf-8"), "database-mcp", "exec")

    def test_only_the_version_line_changes(self):
        before = self.server().read_text(encoding="utf-8").splitlines()
        self.mod.set_version(self.root, "4.5.6")
        after = self.server().read_text(encoding="utf-8").splitlines()

        differing = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
        self.assertEqual(len(differing), 1, "a release commit must not carry other edits")

    def test_applying_the_same_version_twice_is_a_no_op(self):
        self.mod.set_version(self.root, "1.2.3")
        first = tuple(p.read_bytes() for p in (self.manifest(), self.server(), self.page()))
        self.mod.set_version(self.root, "1.2.3")

        self.assertEqual(tuple(p.read_bytes() for p in (self.manifest(), self.server(), self.page())), first)

    def test_rejects_a_version_that_is_not_semver(self):
        for bad in ("v1.2.3", "1.2", "1.2.3-rc1", ""):
            with self.subTest(version=bad):
                with self.assertRaises(SystemExit):
                    self.mod.set_version(self.root, bad)

    def test_fails_loudly_when_a_version_site_is_missing(self):
        server = self.server()
        server.write_text(
            server.read_text(encoding="utf-8").replace('SERVER_VERSION = "', 'RENAMED = "'),
            encoding="utf-8",
        )
        with self.assertRaises(SystemExit):
            self.mod.set_version(self.root, "1.2.3")

    def test_only_if_newer_refuses_to_downgrade(self):
        """A hotfix is usually branched from an older tag, so propagating its
        version onto a main that has moved on would walk the version backwards."""
        self.mod.set_version(self.root, "2.5.0")
        before = self.manifest().read_bytes()

        written = self.mod.set_version(self.root, "1.1.2", only_if_newer=True)

        self.assertEqual(written, [])
        self.assertEqual(self.manifest().read_bytes(), before)
        self.assertEqual(declared_page_version(self.page()), "2.5.0")

    def test_only_if_newer_refuses_the_same_version(self):
        self.mod.set_version(self.root, "2.5.0")

        self.assertEqual(self.mod.set_version(self.root, "2.5.0", only_if_newer=True), [])

    def test_only_if_newer_writes_a_higher_version(self):
        self.mod.set_version(self.root, "1.1.1")

        written = self.mod.set_version(self.root, "1.2.0", only_if_newer=True)

        self.assertEqual(len(written), 3)
        self.assertEqual(declared_page_version(self.page()), "1.2.0")

    def test_only_if_newer_compares_numerically_not_lexically(self):
        # "1.10.0" < "1.9.0" as strings, but 1.10.0 is the newer release.
        self.mod.set_version(self.root, "1.9.0")

        self.assertEqual(len(self.mod.set_version(self.root, "1.10.0", only_if_newer=True)), 3)
        self.assertEqual(self.mod.set_version(self.root, "1.9.0", only_if_newer=True), [])

    def test_plain_set_version_still_overwrites_downwards(self):
        # The release branch itself must always get the computed version, so the
        # tag carries it; only the propagation step guards against downgrades.
        self.mod.set_version(self.root, "2.5.0")

        self.assertEqual(len(self.mod.set_version(self.root, "1.0.0")), 3)
        self.assertEqual(declared_page_version(self.page()), "1.0.0")

    def test_fails_loudly_when_a_version_site_is_duplicated(self):
        server = self.server()
        text = server.read_text(encoding="utf-8")
        server.write_text(text + '\nSERVER_VERSION = "0.0.0"\n', encoding="utf-8")

        with self.assertRaises(SystemExit):
            self.mod.set_version(self.root, "1.2.3")


if __name__ == "__main__":
    unittest.main()
