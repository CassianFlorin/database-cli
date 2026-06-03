import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB_QUERY = ROOT / "scripts" / "db-query"


class DbQueryTest(unittest.TestCase):
    def test_prints_mysql_column_search_command(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Path(tmpdir) / "connections.local.json"
            config.write_text(
                json.dumps(
                    {
                        "environments": {
                            "qa01": {
                                "driver": "mysql",
                                "host": "mysql-qa01.example.internal",
                                "username": "readonly_user",
                            }
                        }
                    }
                ),
                encoding="utf-8",
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


if __name__ == "__main__":
    unittest.main()
