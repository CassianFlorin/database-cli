import json
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB_QUERY = ROOT / "scripts" / "db-query"


def printed_sql(stdout):
    command = [line for line in stdout.splitlines() if line.startswith("sq ")][-1]
    return shlex.split(command)[-1]


class DbQueryTest(unittest.TestCase):
    def write_config(self, tmpdir, env):
        config = Path(tmpdir) / "connections.local.json"
        config.write_text(
            json.dumps({"environments": {"qa01": env}}),
            encoding="utf-8",
        )
        return config

    def test_list_envs_includes_connection_metadata_without_secrets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = self.write_config(
                tmpdir,
                {
                    "display_name": "QNVIP QA01",
                    "environment": "qa01",
                    "project": "qnvip",
                    "description": "Shared QA readonly connection.",
                    "aliases": ["qa-01", "test"],
                    "driver": "mysql",
                    "host": "mysql-qa01.example.internal",
                    "username": "readonly_user",
                    "password": "secret",
                    "password_env": "QA01_DB_PASSWORD",
                    "max_rows": 100,
                },
            )

            result = subprocess.run(
                [str(DB_QUERY), "--config", str(config), "--list-envs"],
                text=True,
                capture_output=True,
                check=True,
            )

            data = json.loads(result.stdout)
            self.assertEqual(data["environments"], ["qa01"])
            self.assertEqual(data["connections"][0]["name"], "qa01")
            self.assertEqual(data["connections"][0]["display_name"], "QNVIP QA01")
            self.assertEqual(data["connections"][0]["environment"], "qa01")
            self.assertEqual(data["connections"][0]["project"], "qnvip")
            self.assertEqual(data["connections"][0]["aliases"], ["qa-01", "test"])
            self.assertEqual(data["connections"][0]["max_rows"], 100)
            self.assertNotIn("password", json.dumps(data))
            self.assertNotIn("QA01_DB_PASSWORD", json.dumps(data))

    def test_env_alias_resolves_to_canonical_connection(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = self.write_config(
                tmpdir,
                {
                    "driver": "mysql",
                    "host": "mysql-qa01.example.internal",
                    "username": "readonly_user",
                    "aliases": ["qa-01", "test"],
                },
            )

            result = subprocess.run(
                [
                    str(DB_QUERY),
                    "--config",
                    str(config),
                    "--env",
                    "qa-01",
                    "--sql",
                    "SELECT 1",
                    "--print-command",
                ],
                text=True,
                capture_output=True,
                check=True,
            )

            self.assertIn("@database_cli_qa01", result.stdout)

    def test_prints_mysql_column_search_command(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = self.write_config(
                tmpdir,
                {
                    "driver": "mysql",
                    "host": "mysql-qa01.example.internal",
                    "username": "readonly_user",
                },
            )

            result = subprocess.run(
                [
                    str(DB_QUERY),
                    "--config",
                    str(config),
                    "--env",
                    "qa01",
                    "--search-objects",
                    "%order_no%",
                    "--object-type",
                    "column",
                    "--table",
                    "cc_order",
                    "--print-command",
                ],
                text=True,
                capture_output=True,
                check=True,
            )

            self.assertIn("INFORMATION_SCHEMA.COLUMNS", result.stdout)
            self.assertIn("COLUMN_NAME LIKE", result.stdout)
            self.assertIn("%order_no%", result.stdout)
            self.assertIn("TABLE_NAME =", result.stdout)
            self.assertIn("cc_order", result.stdout)
            self.assertIn("LIMIT 200", result.stdout)

    def test_prints_mysql_procedure_search_command(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = self.write_config(
                tmpdir,
                {
                    "driver": "mysql",
                    "host": "mysql-qa01.example.internal",
                    "username": "readonly_user",
                },
            )

            result = subprocess.run(
                [
                    str(DB_QUERY),
                    "--config",
                    str(config),
                    "--env",
                    "qa01",
                    "--search-objects",
                    "%sync_order%",
                    "--object-type",
                    "procedure",
                    "--schema",
                    "qnvip_center_commerce",
                    "--print-command",
                ],
                text=True,
                capture_output=True,
                check=True,
            )

            self.assertIn("INFORMATION_SCHEMA.ROUTINES", result.stdout)
            self.assertIn("ROUTINE_NAME LIKE", result.stdout)
            self.assertIn("%sync_order%", result.stdout)
            self.assertIn("ROUTINE_SCHEMA =", result.stdout)
            self.assertIn("qnvip_center_commerce", result.stdout)
            self.assertIn("LIMIT 200", result.stdout)

    def test_prints_mysql_function_search_with_full_detail(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = self.write_config(
                tmpdir,
                {
                    "driver": "mysql",
                    "host": "mysql-qa01.example.internal",
                    "username": "readonly_user",
                },
            )

            result = subprocess.run(
                [
                    str(DB_QUERY),
                    "--config",
                    str(config),
                    "--env",
                    "qa01",
                    "--search-objects",
                    "%calc%",
                    "--object-type",
                    "function",
                    "--detail-level",
                    "full",
                    "--print-command",
                ],
                text=True,
                capture_output=True,
                check=True,
            )

            sql = printed_sql(result.stdout)
            self.assertIn("INFORMATION_SCHEMA.ROUTINES", sql)
            self.assertIn("ROUTINE_TYPE = 'FUNCTION'", sql)
            self.assertIn("ROUTINE_DEFINITION", sql)
            self.assertIn("ROUTINE_COMMENT", sql)

    def test_configured_max_rows_caps_auto_limit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = self.write_config(
                tmpdir,
                {
                    "driver": "mysql",
                    "host": "mysql-qa01.example.internal",
                    "username": "readonly_user",
                    "max_rows": 50,
                },
            )

            result = subprocess.run(
                [
                    str(DB_QUERY),
                    "--config",
                    str(config),
                    "--env",
                    "qa01",
                    "--limit",
                    "500",
                    "--sql",
                    "SELECT id FROM cc_order",
                    "--print-command",
                ],
                text=True,
                capture_output=True,
                check=True,
            )

            self.assertIn("SELECT id FROM cc_order LIMIT 50", result.stdout)

    def test_readonly_false_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = self.write_config(
                tmpdir,
                {
                    "driver": "mysql",
                    "host": "mysql-qa01.example.internal",
                    "username": "readonly_user",
                    "readonly": False,
                },
            )

            result = subprocess.run(
                [
                    str(DB_QUERY),
                    "--config",
                    str(config),
                    "--env",
                    "qa01",
                    "--sql",
                    "SELECT 1",
                    "--print-command",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("readonly=false", result.stderr)


if __name__ == "__main__":
    unittest.main()
