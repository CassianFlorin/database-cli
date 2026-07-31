import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INIT_CONFIG = ROOT / "scripts" / "init-config"


class InitConfigTest(unittest.TestCase):
    def test_help_does_not_expose_importer_flags(self):
        result = subprocess.run(
            [str(INIT_CONFIG), "--help"],
            text=True,
            capture_output=True,
            check=True,
        )

        help_text = result.stdout + result.stderr
        self.assertNotIn("--from-", help_text)

    def test_non_interactive_direct_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "connections.local.json"
            result = subprocess.run(
                [
                    str(INIT_CONFIG),
                    "--output",
                    str(output),
                    "--env",
                    "qa01",
                    "--driver",
                    "mysql",
                    "--host",
                    "mysql-qa01.example.internal",
                    "--username",
                    "readonly_user",
                    "--password-env",
                    "QA01_DB_PASSWORD",
                    "--display-name",
                    "QNVIP QA01",
                    "--environment",
                    "qa01",
                    "--project",
                    "qnvip",
                    "--description",
                    "Shared QA readonly connection.",
                    "--alias",
                    "qa-01",
                    "--alias",
                    "test",
                    "--max-rows",
                    "100",
                    "--non-interactive",
                ],
                text=True,
                capture_output=True,
                check=True,
            )

            self.assertIn("qa01", result.stdout)
            data = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(
                data["environments"]["qa01"],
                {
                    "driver": "mysql",
                    "host": "mysql-qa01.example.internal",
                    "username": "readonly_user",
                    "password_env": "QA01_DB_PASSWORD",
                    "display_name": "QNVIP QA01",
                    "environment": "qa01",
                    "project": "qnvip",
                    "description": "Shared QA readonly connection.",
                    "aliases": ["qa-01", "test"],
                    "max_rows": 100,
                    "limit_style": "limit",
                },
            )

    def test_non_interactive_database_url_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "connections.local.json"
            subprocess.run(
                [
                    str(INIT_CONFIG),
                    "--output",
                    str(output),
                    "--env",
                    "qa03",
                    "--url",
                    "mysql://mysql-qa03.example.internal:3307/qnvip_center_order?charset=utf8mb4",
                    "--username",
                    "readonly_user",
                    "--password",
                    "local-secret",
                    "--non-interactive",
                ],
                text=True,
                capture_output=True,
                check=True,
            )

            data = json.loads(output.read_text(encoding="utf-8"))
            env = data["environments"]["qa03"]
            self.assertEqual(env["driver"], "mysql")
            self.assertEqual(env["host"], "mysql-qa03.example.internal")
            self.assertEqual(env["port"], 3307)
            self.assertEqual(env["database"], "qnvip_center_order")
            self.assertEqual(env["username"], "readonly_user")
            self.assertEqual(env["password"], "local-secret")
            self.assertEqual(env["params"], {"charset": "utf8mb4"})
            self.assertEqual(env["limit_style"], "limit")

    def test_config_alias_writes_output_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "connections.local.json"
            subprocess.run(
                [
                    str(INIT_CONFIG),
                    "--config",
                    str(output),
                    "--env",
                    "qa04",
                    "--url",
                    "mysql://mysql-qa04.example.internal",
                    "--username",
                    "readonly_user",
                    "--password-env",
                    "QA04_DB_PASSWORD",
                    "--non-interactive",
                ],
                text=True,
                capture_output=True,
                check=True,
            )

            data = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(data["environments"]["qa04"]["host"], "mysql-qa04.example.internal")

    def test_install_forwards_init_config_arguments(self):
        install = ROOT / "scripts" / "install"
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "connections.local.json"
            subprocess.run(
                [
                    str(install),
                    "--skip-sq-check",
                    "--config",
                    str(output),
                    "--env",
                    "qa05",
                    "--url",
                    "mysql://mysql-qa05.example.internal",
                    "--username",
                    "readonly_user",
                    "--password-env",
                    "QA05_DB_PASSWORD",
                    "--non-interactive",
                ],
                text=True,
                capture_output=True,
                check=True,
            )

            data = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(data["environments"]["qa05"]["host"], "mysql-qa05.example.internal")


class DefaultOutputPathTest(unittest.TestCase):
    """Where init-config writes when the caller passes no --config/--output.

    Every other test in this file passes --output explicitly, so the default was
    previously unexercised.
    """

    COMMON_ARGS = [
        "--env",
        "qa06",
        "--url",
        "mysql://mysql-qa06.example.internal",
        "--username",
        "readonly_user",
        "--password-env",
        "QA06_DB_PASSWORD",
        "--non-interactive",
    ]

    def _fake_skill_root(self, tmpdir):
        """A stand-in skill root, so a legacy config never lands in the real repo.

        Copied from the skill's own scripts directory rather than the plugin-root
        wrappers: init-config derives its skill root from __file__, and _common.py
        only exists alongside the real script.
        """
        source = ROOT / "skills" / "database-cli" / "scripts"
        skill_root = Path(tmpdir) / "skill"
        (skill_root / "scripts").mkdir(parents=True)
        for name in ("init-config", "_common.py"):
            target = skill_root / "scripts" / name
            target.write_bytes((source / name).read_bytes())
            target.chmod(0o755)
        return skill_root

    def test_defaults_outside_the_repository(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "home"
            home.mkdir()
            skill_root = self._fake_skill_root(tmpdir)

            result = subprocess.run(
                [str(skill_root / "scripts" / "init-config"), *self.COMMON_ARGS],
                text=True,
                capture_output=True,
                check=True,
                env={"HOME": str(home), "PATH": "/usr/bin:/bin:/usr/local/bin"},
            )

            written = Path(json.loads(result.stdout)["written"])
            self.assertEqual(written, home / ".config" / "database-cli" / "connections.json")
            self.assertTrue(written.exists())
            # The directory holds plaintext passwords; group/other must not read it.
            self.assertEqual(written.parent.stat().st_mode & 0o077, 0)
            self.assertEqual(written.stat().st_mode & 0o077, 0)

    def test_an_existing_in_repo_config_keeps_winning_and_warns(self):
        """`_common.config_paths` reads the in-repo file ahead of ~/.config, so
        writing elsewhere while it survives would leave edits with no effect."""
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "home"
            home.mkdir()
            skill_root = self._fake_skill_root(tmpdir)
            legacy = skill_root / "connections.local.json"
            legacy.write_text(
                json.dumps({"environments": {"kept": {"driver": "mysql", "host": "old.example.internal"}}}),
                encoding="utf-8",
            )

            result = subprocess.run(
                [str(skill_root / "scripts" / "init-config"), *self.COMMON_ARGS],
                text=True,
                capture_output=True,
                check=True,
                env={"HOME": str(home), "PATH": "/usr/bin:/bin:/usr/local/bin"},
            )

            # Resolved on both sides: init-config derives its skill root through
            # Path.resolve(), and on macOS /var is a symlink to /private/var.
            self.assertEqual(Path(json.loads(result.stdout)["written"]).resolve(), legacy.resolve())
            self.assertFalse((home / ".config" / "database-cli" / "connections.json").exists())

            data = json.loads(legacy.read_text(encoding="utf-8"))
            self.assertEqual(sorted(data["environments"]), ["kept", "qa06"])

            # The warning must not corrupt the JSON on stdout that callers parse.
            self.assertIn("inside the repository working tree", result.stderr)
            self.assertIn("mv ", result.stderr)


if __name__ == "__main__":
    unittest.main()
