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


if __name__ == "__main__":
    unittest.main()
