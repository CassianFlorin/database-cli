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


def load_setter():
    loader = importlib.machinery.SourceFileLoader(
        "set_version", str(ROOT / ".github" / "scripts" / "set_version.py")
    )
    spec = importlib.util.spec_from_loader("set_version", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def declared_server_version(path=MCP_SERVER):
    match = re.search(r'^SERVER_VERSION = "([^"]*)"$', path.read_text(encoding="utf-8"), re.M)
    return match.group(1) if match else None


class VersionConsistencyTest(unittest.TestCase):
    def test_manifest_and_mcp_server_declare_the_same_version(self):
        manifest = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))["version"]

        self.assertEqual(manifest, declared_server_version())

    def test_declared_version_looks_like_a_release(self):
        manifest = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))["version"]

        self.assertRegex(manifest, r"\A\d+\.\d+\.\d+\Z")


class SetVersionTest(unittest.TestCase):
    def setUp(self):
        self.mod = load_setter()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for source in (PLUGIN_MANIFEST, MCP_SERVER):
            target = self.root / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    def manifest(self):
        return self.root / ".codex-plugin" / "plugin.json"

    def server(self):
        return self.root / "skills" / "database-cli" / "scripts" / "database-mcp"

    def test_writes_the_version_into_both_files(self):
        self.mod.set_version(self.root, "1.2.3")

        self.assertEqual(json.loads(self.manifest().read_text(encoding="utf-8"))["version"], "1.2.3")
        self.assertEqual(declared_server_version(self.server()), "1.2.3")

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
        first = self.manifest().read_bytes(), self.server().read_bytes()
        self.mod.set_version(self.root, "1.2.3")

        self.assertEqual((self.manifest().read_bytes(), self.server().read_bytes()), first)

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

    def test_fails_loudly_when_a_version_site_is_duplicated(self):
        server = self.server()
        text = server.read_text(encoding="utf-8")
        server.write_text(text + '\nSERVER_VERSION = "0.0.0"\n', encoding="utf-8")

        with self.assertRaises(SystemExit):
            self.mod.set_version(self.root, "1.2.3")


if __name__ == "__main__":
    unittest.main()
