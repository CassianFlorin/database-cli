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


if __name__ == "__main__":
    unittest.main()
