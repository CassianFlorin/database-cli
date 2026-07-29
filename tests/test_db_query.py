import importlib.machinery
import importlib.util
import json
import shlex
import subprocess
import sys
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

    def test_setup_status_reports_ready_state_without_secrets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = self.write_config(
                tmpdir,
                {
                    "display_name": "QNVIP QA01",
                    "environment": "qa01",
                    "project": "qnvip",
                    "description": "Shared QA readonly connection.",
                    "aliases": ["qa-01"],
                    "driver": "mysql",
                    "host": "mysql-qa01.example.internal",
                    "username": "readonly_user",
                    "password": "secret",
                    "password_env": "QA01_DB_PASSWORD",
                    "max_rows": 100,
                },
            )

            result = subprocess.run(
                [
                    str(DB_QUERY),
                    "--config",
                    str(config),
                    "--sq-bin",
                    sys.executable,
                    "--setup-status",
                ],
                text=True,
                capture_output=True,
                check=True,
            )

            data = json.loads(result.stdout)
            self.assertTrue(data["ready"])
            self.assertTrue(data["sq_available"])
            self.assertEqual(data["config"]["path"], str(config))
            self.assertEqual(data["environments"], ["qa01"])
            self.assertEqual(data["connections"][0]["name"], "qa01")
            self.assertEqual(data["connections"][0]["display_name"], "QNVIP QA01")
            self.assertEqual(data["next_actions"][0]["command"], "scripts/db-query --list-envs")
            self.assertNotIn("password", json.dumps(data))
            self.assertNotIn("QA01_DB_PASSWORD", json.dumps(data))
            self.assertNotIn("secret", json.dumps(data))

    def test_setup_status_reports_missing_config_as_actionable_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / "missing-connections.json"
            result = subprocess.run(
                [
                    str(DB_QUERY),
                    "--config",
                    str(missing),
                    "--sq-bin",
                    "definitely-missing-sq-for-test",
                    "--setup-status",
                ],
                text=True,
                capture_output=True,
                check=True,
            )

            data = json.loads(result.stdout)
            self.assertFalse(data["ready"])
            self.assertFalse(data["config"]["exists"])
            self.assertFalse(data["sq_available"])
            problem_codes = {problem["code"] for problem in data["problems"]}
            self.assertIn("missing_config", problem_codes)
            self.assertIn("missing_sq", problem_codes)
            commands = [action["command"] for action in data["next_actions"]]
            self.assertIn("brew install sq", commands)
            self.assertTrue(any(command.startswith("scripts/install --env") for command in commands))

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

    def test_ad_hoc_connection_can_query_without_config_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / "missing-connections.json"
            result = subprocess.run(
                [
                    str(DB_QUERY),
                    "--config",
                    str(missing),
                    "--url",
                    "mysql://mysql-adhoc.example.internal:3307/qnvip_center_order?charset=utf8mb4",
                    "--username",
                    "readonly_user",
                    "--password",
                    "local-secret",
                    "--sql",
                    "SELECT 1",
                    "--print-command",
                ],
                text=True,
                capture_output=True,
                check=True,
            )

            self.assertIn("@database_cli_adhoc", result.stdout)
            self.assertIn("mysql-adhoc.example.internal:3307", result.stdout)
            self.assertIn("qnvip_center_order", result.stdout)
            self.assertIn("SELECT 1 LIMIT 200", result.stdout)
            self.assertNotIn("local-secret", result.stdout)

    def test_write_sql_is_rejected_without_explicit_allow_write(self):
        result = subprocess.run(
            [
                str(DB_QUERY),
                "--check-sql",
                "UPDATE cc_order SET status = 1 WHERE id = 10",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("SQL must start with a read-only token", result.stderr)

    def test_write_sql_is_allowed_only_with_explicit_allow_write(self):
        result = subprocess.run(
            [
                str(DB_QUERY),
                "--allow-write",
                "--check-sql",
                "UPDATE cc_order SET status = 1 WHERE id = 10",
            ],
            text=True,
            capture_output=True,
            check=True,
        )

        self.assertEqual(result.stdout.strip(), "UPDATE cc_order SET status = 1 WHERE id = 10")

    def test_approved_update_and_delete_still_require_where_clause(self):
        result = subprocess.run(
            [
                str(DB_QUERY),
                "--allow-write",
                "--check-sql",
                "DELETE FROM cc_order",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("requires a WHERE clause", result.stderr)

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


class AuditLogTest(unittest.TestCase):
    """Audit logging runs around real execution, so these tests stub `sq`.

    Setting `source` on the env makes prepare_source short-circuit the
    `sq add` step, leaving the fake binary as the only invoked command.
    """

    def make_fake_sq(self, tmpdir):
        fake = Path(tmpdir) / "fake-sq"
        fake.write_text(
            "#!/usr/bin/env python3\n"
            "import sys, json\n"
            "sql = sys.argv[-1] if len(sys.argv) > 1 else ''\n"
            # The pre-write row count needs a parseable answer.
            "print(json.dumps([{'affected_rows': 1}]) if 'COUNT(*)' in sql else '[]')\n",
            encoding="utf-8",
        )
        fake.chmod(0o755)
        return fake

    def write_config(self, tmpdir, env):
        config = Path(tmpdir) / "connections.local.json"
        config.write_text(
            json.dumps({"environments": {"qa01": env}}),
            encoding="utf-8",
        )
        return config

    def run_db_query(self, tmpdir, sql_args, env=None, extra=None):
        env = env or {"source": "@qa01", "driver": "mysql"}
        config = self.write_config(tmpdir, env)
        fake = self.make_fake_sq(tmpdir)
        audit = Path(tmpdir) / "audit.log"
        cmd = [
            str(DB_QUERY),
            "--config", str(config),
            "--env", "qa01",
            "--sq-bin", str(fake),
            "--audit-log", str(audit),
        ]
        if extra:
            cmd.extend(extra)
        cmd.extend(sql_args)
        result = subprocess.run(cmd, text=True, capture_output=True, check=False)
        return result, audit

    def read_entries(self, audit):
        return [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_read_query_is_recorded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result, audit = self.run_db_query(tmpdir, ["--sql", "SELECT id FROM cc_order WHERE id = 1"])
            self.assertEqual(result.returncode, 0, result.stderr)
            entries = self.read_entries(audit)
            self.assertEqual(len(entries), 1)
            entry = entries[0]
            self.assertEqual(entry["event"], "sql")
            self.assertEqual(entry["mode"], "read")
            self.assertEqual(entry["token"], "select")
            self.assertEqual(entry["env"], "qa01")
            self.assertFalse(entry["adhoc"])
            self.assertFalse(entry["allow_write"])
            self.assertEqual(entry["exit_code"], 0)
            self.assertIn("SELECT id FROM cc_order", entry["statement"])
            self.assertIn("ts", entry)
            self.assertIsInstance(entry["duration_ms"], (int, float))

    def test_write_query_is_recorded_as_write(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result, audit = self.run_db_query(
                tmpdir,
                ["--sql", "UPDATE cc_order SET status = 1 WHERE id = 1"],
                env={"source": "@qa01", "driver": "mysql", "writable": True},
                extra=["--allow-write"],
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            entry = self.read_entries(audit)[0]
            self.assertEqual(entry["mode"], "write")
            self.assertEqual(entry["token"], "update")
            self.assertTrue(entry["allow_write"])

    def test_secret_is_redacted_from_statement(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {"source": "@qa01", "driver": "mysql", "password": "topsecret"}
            result, audit = self.run_db_query(
                tmpdir,
                ["--sql", "SELECT 'topsecret' AS token"],
                env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            entry = self.read_entries(audit)[0]
            self.assertNotIn("topsecret", entry["statement"])
            self.assertIn("***", entry["statement"])

    def test_ad_hoc_connection_marks_env_null(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fake = self.make_fake_sq(tmpdir)
            audit = Path(tmpdir) / "audit.log"
            result = subprocess.run(
                [
                    str(DB_QUERY),
                    "--url", "mysql://host/db",
                    "--username", "readonly_user",
                    "--sq-bin", str(fake),
                    "--audit-log", str(audit),
                    "--sql", "SELECT 1",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            entry = self.read_entries(audit)[0]
            self.assertIsNone(entry["env"])
            self.assertTrue(entry["adhoc"])

    def test_no_audit_flag_disables_logging(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result, audit = self.run_db_query(
                tmpdir,
                ["--sql", "SELECT 1"],
                extra=["--no-audit"],
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(audit.exists())

    def test_audit_disabled_via_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {"source": "@qa01", "driver": "mysql", "audit": False}
            result, audit = self.run_db_query(tmpdir, ["--sql", "SELECT 1"], env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(audit.exists())

    def test_print_command_does_not_write_audit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result, audit = self.run_db_query(
                tmpdir,
                ["--sql", "SELECT 1"],
                extra=["--print-command"],
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(audit.exists())


class PreviewWriteTest(unittest.TestCase):
    def write_config(self, tmpdir, env):
        config = Path(tmpdir) / "connections.local.json"
        config.write_text(json.dumps({"environments": {"qa01": env}}), encoding="utf-8")
        return config

    def derived_sqls(self, tmpdir, dml, env=None):
        """Return (count_sql, snapshot_sql) via --print-command (no sq needed)."""
        env = env or {"source": "@qa01", "driver": "mysql"}
        config = self.write_config(tmpdir, env)
        result = subprocess.run(
            [
                str(DB_QUERY),
                "--config", str(config),
                "--env", "qa01",
                "--no-audit",
                "--print-command",
                "--preview-write", dml,
            ],
            text=True,
            capture_output=True,
            check=True,
        )
        sq_lines = [line for line in result.stdout.splitlines() if line.startswith("sq ")]
        self.assertEqual(len(sq_lines), 2, result.stdout)
        return shlex.split(sq_lines[0])[-1], shlex.split(sq_lines[1])[-1]

    def test_update_derives_count_and_snapshot(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            count_sql, snapshot_sql = self.derived_sqls(
                tmpdir, "UPDATE cc_order SET status = 1 WHERE order_no = 'YP1'"
            )
            self.assertEqual(
                count_sql,
                "SELECT COUNT(*) AS affected_rows FROM cc_order WHERE order_no = 'YP1'",
            )
            self.assertEqual(
                snapshot_sql,
                "SELECT * FROM cc_order WHERE order_no = 'YP1' LIMIT 200",
            )

    def test_delete_derives_count_and_snapshot(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            count_sql, snapshot_sql = self.derived_sqls(
                tmpdir, "DELETE FROM cc_order WHERE id = 3"
            )
            self.assertEqual(count_sql, "SELECT COUNT(*) AS affected_rows FROM cc_order WHERE id = 3")
            self.assertEqual(snapshot_sql, "SELECT * FROM cc_order WHERE id = 3 LIMIT 200")

    def test_subquery_where_does_not_confuse_top_level_where(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            count_sql, snapshot_sql = self.derived_sqls(
                tmpdir,
                "UPDATE cc_order SET status = 9 WHERE id IN (SELECT id FROM cc_ref WHERE flag = 1)",
            )
            self.assertEqual(
                count_sql,
                "SELECT COUNT(*) AS affected_rows FROM cc_order "
                "WHERE id IN (SELECT id FROM cc_ref WHERE flag = 1)",
            )
            self.assertTrue(snapshot_sql.endswith("WHERE id IN (SELECT id FROM cc_ref WHERE flag = 1) LIMIT 200"))

    def test_where_containing_literal_where_keyword_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            count_sql, _ = self.derived_sqls(
                tmpdir, "UPDATE t SET a = 1 WHERE note = 'set where from'"
            )
            self.assertEqual(
                count_sql,
                "SELECT COUNT(*) AS affected_rows FROM t WHERE note = 'set where from'",
            )

    def test_insert_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = self.write_config(tmpdir, {"source": "@qa01", "driver": "mysql"})
            result = subprocess.run(
                [
                    str(DB_QUERY), "--config", str(config), "--env", "qa01",
                    "--no-audit", "--print-command",
                    "--preview-write", "INSERT INTO t (a) VALUES (1)",
                ],
                text=True, capture_output=True, check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("UPDATE and DELETE", result.stderr)

    def test_update_without_where_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = self.write_config(tmpdir, {"source": "@qa01", "driver": "mysql"})
            result = subprocess.run(
                [
                    str(DB_QUERY), "--config", str(config), "--env", "qa01",
                    "--no-audit", "--print-command",
                    "--preview-write", "UPDATE t SET a = 1",
                ],
                text=True, capture_output=True, check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("WHERE", result.stderr)

    def make_fake_sq(self, tmpdir):
        fake = Path(tmpdir) / "fake-sq"
        fake.write_text("#!/usr/bin/env python3\nprint('[]')\n", encoding="utf-8")
        fake.chmod(0o755)
        return fake

    def test_preview_emits_envelope_and_audits_as_read(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = self.write_config(tmpdir, {"source": "@qa01", "driver": "mysql"})
            fake = self.make_fake_sq(tmpdir)
            audit = Path(tmpdir) / "audit.log"
            result = subprocess.run(
                [
                    str(DB_QUERY), "--config", str(config), "--env", "qa01",
                    "--sq-bin", str(fake), "--audit-log", str(audit),
                    "--preview-write", "DELETE FROM cc_order WHERE id = 5",
                ],
                text=True, capture_output=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            envelope = json.loads(result.stdout)
            self.assertTrue(envelope["preview"])
            self.assertEqual(envelope["token"], "delete")
            self.assertEqual(envelope["from"], "cc_order")
            self.assertEqual(envelope["where"], "id = 5")
            self.assertIn("snapshot", envelope)

            entry = json.loads(audit.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(entry["event"], "preview_write")
            self.assertEqual(entry["mode"], "read")
            self.assertFalse(entry["allow_write"])


class GenerateRollbackTest(unittest.TestCase):
    def write_config(self, tmpdir, env):
        config = Path(tmpdir) / "connections.local.json"
        config.write_text(json.dumps({"environments": {"qa01": env}}), encoding="utf-8")
        return config

    def make_fake_sq(self, tmpdir, rows, count=None):
        """Fake sq: COUNT queries return the count; snapshot queries return rows."""
        count = len(rows) if count is None else count
        script = (
            "#!/usr/bin/env python3\n"
            "import sys, json\n"
            f"rows = json.loads(r'''{json.dumps(rows)}''')\n"
            f"count = {count}\n"
            "sql = sys.argv[-1] if len(sys.argv) > 1 else ''\n"
            "if 'COUNT(*)' in sql:\n"
            "    print(json.dumps([{'affected_rows': count}]))\n"
            "else:\n"
            "    print(json.dumps(rows))\n"
        )
        fake = Path(tmpdir) / "fake-sq"
        fake.write_text(script, encoding="utf-8")
        fake.chmod(0o755)
        return fake

    def run_rollback(self, tmpdir, dml, rows, count=None, extra=None, env=None):
        env = env or {"source": "@qa01", "driver": "mysql"}
        config = self.write_config(tmpdir, env)
        fake = self.make_fake_sq(tmpdir, rows, count)
        audit = Path(tmpdir) / "audit.log"
        cmd = [
            str(DB_QUERY), "--config", str(config), "--env", "qa01",
            "--sq-bin", str(fake), "--audit-log", str(audit),
            "--generate-rollback", dml,
        ]
        if extra:
            cmd.extend(extra)
        result = subprocess.run(cmd, text=True, capture_output=True, check=False)
        return result, audit

    def test_update_rollback_restores_old_values_scoped_by_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [{"id": 1, "order_no": "YP1", "status": 0}, {"id": 2, "order_no": "YP2", "status": 0}]
            result, audit = self.run_rollback(
                tmpdir,
                "UPDATE cc_order SET status = 9 WHERE status = 0",
                rows,
                extra=["--key-columns", "id"],
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            envelope = json.loads(result.stdout)
            self.assertTrue(envelope["rollback"])
            self.assertFalse(envelope["executed"])
            self.assertEqual(envelope["table"], "cc_order")
            self.assertEqual(envelope["set_columns"], ["status"])
            self.assertEqual(
                envelope["rollback_sql"],
                [
                    "UPDATE cc_order SET status = 0 WHERE id = 1;",
                    "UPDATE cc_order SET status = 0 WHERE id = 2;",
                ],
            )
            entry = json.loads(audit.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(entry["event"], "generate_rollback")
            self.assertEqual(entry["mode"], "read")

    def test_delete_rollback_reinserts_rows_with_nulls_and_quotes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [{"id": 1, "note": None}, {"id": 2, "note": "a'b"}]
            result, _ = self.run_rollback(tmpdir, "DELETE FROM cc_order WHERE id IN (1, 2)", rows)
            self.assertEqual(result.returncode, 0, result.stderr)
            envelope = json.loads(result.stdout)
            self.assertEqual(
                envelope["rollback_sql"],
                [
                    "INSERT INTO cc_order (id, note) VALUES (1, NULL);",
                    "INSERT INTO cc_order (id, note) VALUES (2, 'a''b');",
                ],
            )

    def test_update_rollback_requires_key_columns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result, _ = self.run_rollback(
                tmpdir, "UPDATE cc_order SET status = 9 WHERE id = 1", [{"id": 1, "status": 0}]
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("key-columns", result.stderr)

    def test_insert_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result, _ = self.run_rollback(tmpdir, "INSERT INTO t (a) VALUES (1)", [])
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("UPDATE and DELETE", result.stderr)

    def test_aliased_or_joined_table_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result, _ = self.run_rollback(
                tmpdir,
                "DELETE o FROM cc_order o WHERE o.id = 1",
                [{"id": 1}],
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("single", result.stderr.lower())

    def test_partial_rollback_is_refused_when_snapshot_truncated(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result, _ = self.run_rollback(
                tmpdir,
                "DELETE FROM cc_order WHERE status = 0",
                [{"id": 1, "status": 0}],
                count=5,
                extra=["--max-rows", "1"],
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("partial rollback", result.stderr.lower())

    def test_backslash_values_are_escaped_for_the_configured_driver(self):
        rows = [{"id": 1, "note": "ends with \\"}]
        with tempfile.TemporaryDirectory() as tmpdir:
            result, _ = self.run_rollback(
                tmpdir, "UPDATE t SET note = 'x' WHERE id = 1", rows,
                extra=["--key-columns", "id"],
                env={"source": "@qa01", "driver": "mysql"},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                json.loads(result.stdout)["rollback_sql"],
                ["UPDATE t SET note = 'ends with \\\\' WHERE id = 1;"],
            )

    def test_backslash_values_are_refused_when_the_driver_is_unknown(self):
        rows = [{"id": 1, "note": "ends with \\"}]
        with tempfile.TemporaryDirectory() as tmpdir:
            result, _ = self.run_rollback(
                tmpdir, "UPDATE t SET note = 'x' WHERE id = 1", rows,
                extra=["--key-columns", "id"],
                env={"source": "@qa01"},
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("without knowing the driver", result.stderr)

    def test_composite_key_and_multi_column_set(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [{"tenant": 7, "id": 1, "a": "x", "b": 2}]
            result, _ = self.run_rollback(
                tmpdir,
                "UPDATE t SET a = 'new', b = 9 WHERE id = 1",
                rows,
                extra=["--key-columns", "tenant,id"],
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            envelope = json.loads(result.stdout)
            self.assertEqual(
                envelope["rollback_sql"],
                ["UPDATE t SET a = 'x', b = 2 WHERE tenant = 7 AND id = 1;"],
            )


class RepairTest(unittest.TestCase):
    def write_config(self, tmpdir, env):
        config = Path(tmpdir) / "connections.local.json"
        config.write_text(json.dumps({"environments": {"qa01": env}}), encoding="utf-8")
        return config

    def make_fake_sq(self, tmpdir, rows, count=None):
        count = len(rows) if count is None else count
        script = (
            "#!/usr/bin/env python3\n"
            "import sys, json\n"
            f"rows = json.loads(r'''{json.dumps(rows)}''')\n"
            f"count = {count}\n"
            "sql = sys.argv[-1] if len(sys.argv) > 1 else ''\n"
            "if 'COUNT(*)' in sql:\n"
            "    print(json.dumps([{'affected_rows': count}]))\n"
            "else:\n"
            "    print(json.dumps(rows))\n"
        )
        fake = Path(tmpdir) / "fake-sq"
        fake.write_text(script, encoding="utf-8")
        fake.chmod(0o755)
        return fake

    def run_repair(self, tmpdir, dml, rows, count=None, extra=None, env=None):
        config = self.write_config(tmpdir, env or {"source": "@qa01", "driver": "mysql", "writable": True})
        fake = self.make_fake_sq(tmpdir, rows, count)
        audit = Path(tmpdir) / "audit.log"
        cmd = [
            str(DB_QUERY), "--config", str(config), "--env", "qa01",
            "--sq-bin", str(fake), "--audit-log", str(audit),
            "--repair", dml,
        ]
        if extra:
            cmd.extend(extra)
        result = subprocess.run(cmd, text=True, capture_output=True, check=False)
        return result, audit

    def test_dry_package_assembles_all_parts_without_executing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [{"id": 1, "status": 0}, {"id": 2, "status": 0}]
            result, audit = self.run_repair(
                tmpdir, "UPDATE cc_order SET status = 1 WHERE status = 0", rows,
                extra=["--key-columns", "id"],
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            pkg = json.loads(result.stdout)
            self.assertTrue(pkg["repair"])
            self.assertFalse(pkg["executed"])
            self.assertEqual(pkg["change_sql"], "UPDATE cc_order SET status = 1 WHERE status = 0")
            self.assertIn("snapshot", pkg["pre_check"])
            self.assertEqual(
                pkg["rollback_sql"],
                ["UPDATE cc_order SET status = 0 WHERE id = 1;", "UPDATE cc_order SET status = 0 WHERE id = 2;"],
            )
            self.assertEqual(pkg["post_check_sql"], "SELECT * FROM cc_order WHERE (id = 1) OR (id = 2)")
            self.assertIn("note", pkg)
            self.assertNotIn("change_result", pkg)
            entry = json.loads(audit.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(entry["event"], "repair")
            self.assertEqual(entry["mode"], "read")
            self.assertFalse(entry["executed"])

    def test_executed_path_runs_change_and_post_check(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [{"id": 1, "status": 0}]
            result, audit = self.run_repair(
                tmpdir, "UPDATE cc_order SET status = 1 WHERE id = 1", rows,
                extra=["--key-columns", "id", "--allow-write"],
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            pkg = json.loads(result.stdout)
            self.assertTrue(pkg["executed"])
            self.assertEqual(pkg["change_result"]["exit_code"], 0)
            self.assertIn("post_check", pkg)
            self.assertEqual(pkg["post_check"]["exit_code"], 0)
            entry = json.loads(audit.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(entry["mode"], "write")
            self.assertTrue(entry["executed"])

    def test_execution_is_refused_above_the_write_cap(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [{"id": 1, "status": 0}, {"id": 2, "status": 0}]
            result, _ = self.run_repair(
                tmpdir, "UPDATE cc_order SET status = 1 WHERE status = 0", rows,
                extra=["--key-columns", "id", "--allow-write"],
                env={"source": "@qa01", "driver": "mysql", "writable": True, "max_write_rows": 1},
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("would affect 2 rows", result.stderr)
            self.assertIn("1-row write cap", result.stderr)

    def test_readonly_package_is_not_capped(self):
        # A package for human review is planning material; only execution is capped.
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [{"id": 1, "status": 0}, {"id": 2, "status": 0}]
            result, _ = self.run_repair(
                tmpdir, "UPDATE cc_order SET status = 1 WHERE status = 0", rows,
                extra=["--key-columns", "id"],
                env={"source": "@qa01", "driver": "mysql", "max_write_rows": 1},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(json.loads(result.stdout)["executed"])


    def test_delete_repair_uses_remaining_count_post_check(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [{"id": 1, "note": None}]
            result, _ = self.run_repair(tmpdir, "DELETE FROM cc_order WHERE id = 1", rows)
            self.assertEqual(result.returncode, 0, result.stderr)
            pkg = json.loads(result.stdout)
            self.assertEqual(pkg["rollback_sql"], ["INSERT INTO cc_order (id, note) VALUES (1, NULL);"])
            self.assertEqual(pkg["post_check_sql"], "SELECT COUNT(*) AS remaining FROM cc_order WHERE id = 1")

    def test_update_repair_requires_key_columns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result, _ = self.run_repair(
                tmpdir, "UPDATE cc_order SET status = 1 WHERE id = 1", [{"id": 1, "status": 0}]
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("key-columns", result.stderr)

    def test_partial_repair_is_refused_when_truncated(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result, _ = self.run_repair(
                tmpdir, "DELETE FROM cc_order WHERE status = 0",
                [{"id": 1, "status": 0}], count=9, extra=["--max-rows", "1"],
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("repair package", result.stderr.lower())

    def test_print_command_emits_precheck_snapshot_and_change(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = self.write_config(tmpdir, {"source": "@qa01", "driver": "mysql"})
            result = subprocess.run(
                [
                    str(DB_QUERY), "--config", str(config), "--env", "qa01",
                    "--no-audit", "--print-command",
                    "--repair", "DELETE FROM cc_order WHERE id = 7",
                ],
                text=True, capture_output=True, check=True,
            )
            sq_lines = [line for line in result.stdout.splitlines() if line.startswith("sq ")]
            self.assertEqual(len(sq_lines), 3, result.stdout)
            self.assertIn("COUNT(*)", sq_lines[0])
            self.assertIn("SELECT * FROM cc_order WHERE id = 7", shlex.split(sq_lines[1])[-1])
            self.assertEqual(shlex.split(sq_lines[2])[-1], "DELETE FROM cc_order WHERE id = 7")


class DeniedConnectionParamTest(unittest.TestCase):
    """Some driver parameters would undo the wrapper's guarantees from the outside."""

    def run_with_param(self, param):
        return subprocess.run(
            [
                str(DB_QUERY),
                "--url", f"mysql://mysql-qa01.example.internal/db?{param}",
                "--username", "readonly_user",
                "--print-command",
                "--sql", "SELECT 1",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_multi_statements_is_refused(self):
        result = self.run_with_param("multiStatements=true")

        self.assertEqual(result.returncode, 2)
        self.assertIn("multiStatements", result.stderr)
        self.assertIn("single-statement check", result.stderr)

    def test_local_file_access_is_refused(self):
        result = self.run_with_param("allowAllFiles=true")

        self.assertEqual(result.returncode, 2)
        self.assertIn("LOAD DATA LOCAL INFILE", result.stderr)

    def test_credential_weakening_params_are_refused(self):
        for param in ("allowCleartextPasswords=true", "allowOldPasswords=true",
                      "allowFallbackToPlaintext=true"):
            with self.subTest(param=param):
                result = self.run_with_param(param)
                self.assertEqual(result.returncode, 2)
                self.assertIn("is not allowed", result.stderr)

    def test_matching_is_case_insensitive(self):
        result = self.run_with_param("MULTISTATEMENTS=true")

        self.assertEqual(result.returncode, 2)
        self.assertIn("is not allowed", result.stderr)

    def test_disabling_value_is_accepted(self):
        # multiStatements=false is what this tool wants anyway.
        result = self.run_with_param("multiStatements=false")

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_ordinary_params_still_pass_through(self):
        result = self.run_with_param("charset=utf8mb4")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("charset=utf8mb4", result.stdout)

    def test_denied_param_in_config_is_refused(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Path(tmpdir) / "connections.local.json"
            config.write_text(
                json.dumps(
                    {
                        "environments": {
                            "qa01": {
                                "driver": "mysql",
                                "host": "h",
                                "username": "u",
                                "params": {"multiStatements": "true"},
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                [str(DB_QUERY), "--config", str(config), "--env", "qa01",
                 "--print-command", "--sql", "SELECT 1"],
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("is not allowed", result.stderr)

    def test_sqlserver_params_are_checked_too(self):
        """The sqlserver branch builds its query string without filter_params."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Path(tmpdir) / "connections.local.json"
            config.write_text(
                json.dumps(
                    {
                        "environments": {
                            "mssql": {
                                "driver": "sqlserver",
                                "host": "h",
                                "username": "u",
                                "params": {"allowAllFiles": "true"},
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                [str(DB_QUERY), "--config", str(config), "--env", "mssql",
                 "--print-command", "--sql", "SELECT 1"],
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("is not allowed", result.stderr)


class AuditLogPermissionTest(unittest.TestCase):
    """The log stores executed SQL, whose WHERE clauses routinely carry personal data."""

    def run_query(self, tmpdir, audit):
        config = Path(tmpdir) / "connections.local.json"
        config.write_text(
            json.dumps({"environments": {"qa01": {"source": "@qa01", "driver": "mysql"}}}),
            encoding="utf-8",
        )
        return subprocess.run(
            [str(DB_QUERY), "--config", str(config), "--env", "qa01",
             "--sq-bin", "/bin/echo", "--audit-log", str(audit), "--sql", "SELECT 1"],
            text=True,
            capture_output=True,
            check=False,
        )

    def mode(self, path):
        import stat as stat_module

        return stat_module.S_IMODE(path.stat().st_mode)

    def test_new_log_and_directory_are_owner_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            audit = Path(tmpdir) / "state" / "audit.log"
            self.assertEqual(self.run_query(tmpdir, audit).returncode, 0)

            self.assertEqual(self.mode(audit), 0o600)
            self.assertEqual(self.mode(audit.parent), 0o700)

    def test_log_left_world_readable_by_an_older_version_is_tightened(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            audit = Path(tmpdir) / "audit.log"
            audit.write_text("", encoding="utf-8")
            audit.chmod(0o644)

            self.assertEqual(self.run_query(tmpdir, audit).returncode, 0)
            self.assertEqual(self.mode(audit), 0o600)

    def test_entries_are_still_appended(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            audit = Path(tmpdir) / "audit.log"
            self.run_query(tmpdir, audit)
            self.run_query(tmpdir, audit)

            lines = [line for line in audit.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(lines), 2)
            self.assertEqual(json.loads(lines[0])["event"], "sql")


class ShowStatementTest(unittest.TestCase):
    """SHOW names objects whose names collide with the forbidden-keyword list."""

    def check(self, sql, extra=None):
        return subprocess.run(
            [str(DB_QUERY), *(extra or []), "--check-sql", sql],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_show_create_table_is_allowed(self):
        result = self.check("SHOW CREATE TABLE users")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "SHOW CREATE TABLE users")

    def test_other_show_forms_naming_reserved_words_are_allowed(self):
        for sql in (
            "SHOW GRANTS FOR CURRENT_USER",
            "SHOW ENGINE INNODB STATUS",
            "SHOW CREATE VIEW v",
            "SHOW CREATE PROCEDURE p",
            "SHOW TABLE STATUS",
            "SHOW BINARY LOGS",
        ):
            with self.subTest(sql=sql):
                self.assertEqual(self.check(sql).returncode, 0)

    def test_show_still_rejects_side_effect_patterns(self):
        result = self.check("SHOW CREATE TABLE users /* */ WHERE sleep(5)")

        self.assertEqual(result.returncode, 2)
        self.assertIn("blocked pattern", result.stderr)

    def test_show_is_still_one_statement_only(self):
        result = self.check("SHOW CREATE TABLE users; DROP TABLE users")

        self.assertEqual(result.returncode, 2)
        self.assertIn("exactly one statement", result.stderr)

    def test_explain_analyze_update_stays_blocked(self):
        """EXPLAIN ANALYZE UPDATE really executes the statement on MySQL 8, so
        the relaxation must not extend from SHOW to EXPLAIN."""
        result = self.check("EXPLAIN ANALYZE UPDATE cc_order SET status = 1 WHERE id = 1")

        self.assertEqual(result.returncode, 2)
        self.assertIn("blocked keyword", result.stderr)

    def test_explain_hides_dml_from_every_first_token_guard(self):
        """An EXPLAIN's first token is `explain`, so the WHERE requirement, the
        affected-row cap, and the audit read/write split all skip it. Under
        --allow-write the DML keywords used to be subtracted from the forbidden
        set, which let `EXPLAIN ANALYZE DELETE FROM t` through with no WHERE at
        all -- and MySQL 8.0.18+ executes it."""
        for sql in (
            "EXPLAIN ANALYZE DELETE FROM cc_order",
            "EXPLAIN ANALYZE DELETE FROM cc_order WHERE id = 1",
            "EXPLAIN ANALYZE UPDATE cc_order SET status = 1 WHERE id = 1",
            "EXPLAIN DELETE FROM cc_order",
        ):
            with self.subTest(sql=sql):
                result = self.check(sql, extra=["--allow-write"])
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertIn("blocked keyword", result.stderr)

    def test_explain_analyze_select_is_still_allowed(self):
        for extra in ([], ["--allow-write"]):
            with self.subTest(extra=extra):
                result = self.check(
                    "EXPLAIN ANALYZE SELECT id FROM cc_order WHERE id = 1", extra=extra
                )
                self.assertEqual(result.returncode, 0, result.stderr)


class SqlLiteralTest(unittest.TestCase):
    """Rollback literals must restore the original value on the target dialect.

    MySQL reads a backslash inside a string literal as an escape, so
    `'ends with \\'` swallowed the closing quote and shifted every following
    value. Postgres reads it literally, where doubling would corrupt the value
    instead — so one escaping rule cannot serve both.
    """

    @classmethod
    def setUpClass(cls):
        loader = importlib.machinery.SourceFileLoader(
            "db_query", str(ROOT / "skills" / "database-cli" / "scripts" / "db-query")
        )
        spec = importlib.util.spec_from_loader("db_query", loader)
        cls.mod = importlib.util.module_from_spec(spec)
        loader.exec_module(cls.mod)

    def test_mysql_escapes_the_backslash(self):
        self.assertEqual(self.mod.sql_literal("ends with \\", "mysql"), "'ends with \\\\'")
        self.assertEqual(self.mod.sql_literal("ends with \\", "mariadb"), "'ends with \\\\'")
        self.assertEqual(self.mod.sql_literal("ends with \\", "clickhouse"), "'ends with \\\\'")

    def test_standard_dialects_leave_the_backslash_alone(self):
        for driver in ("postgres", "postgresql", "sqlite3", "duckdb", "sqlserver"):
            with self.subTest(driver=driver):
                self.assertEqual(self.mod.sql_literal("ends with \\", driver), "'ends with \\'")

    def test_quote_doubling_applies_everywhere(self):
        for driver in ("mysql", "postgres", ""):
            with self.subTest(driver=driver):
                self.assertEqual(self.mod.sql_literal("O'Brien", driver), "'O''Brien'")

    def test_unknown_driver_refuses_only_backslash_values(self):
        self.assertEqual(self.mod.sql_literal("plain value", ""), "'plain value'")
        with self.assertRaises(self.mod.UnsafeSqlError) as ctx:
            self.mod.sql_literal("a\\b", "")
        self.assertIn("without knowing the driver", str(ctx.exception))

    def test_mysql_escapes_an_embedded_nul(self):
        self.assertEqual(self.mod.sql_literal("a\0b", "mysql"), "'a\\0b'")

    def test_non_finite_floats_are_refused(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                with self.assertRaises(self.mod.UnsafeSqlError):
                    self.mod.sql_value_literal(value, "mysql")

    def test_json_columns_round_trip_as_json_text(self):
        self.assertEqual(
            self.mod.sql_value_literal({"b": "x'y", "a": 1}, "mysql"),
            "'{\"a\": 1, \"b\": \"x''y\"}'",
        )

    def test_scalars_keep_their_existing_forms(self):
        self.assertEqual(self.mod.sql_value_literal(None, "mysql"), "NULL")
        self.assertEqual(self.mod.sql_value_literal(True, "mysql"), "TRUE")
        self.assertEqual(self.mod.sql_value_literal(7, "mysql"), "7")
        self.assertEqual(self.mod.sql_value_literal(1.5, "mysql"), "1.5")

    def test_rollback_statements_carry_the_escaping_end_to_end(self):
        rows = [{"id": 1, "note": "ends with \\", "status": "old"}]
        self.assertEqual(
            self.mod.build_update_rollback("t", ["note"], ["id"], rows, "mysql"),
            ["UPDATE t SET note = 'ends with \\\\' WHERE id = 1;"],
        )
        self.assertEqual(
            self.mod.build_delete_rollback("t", rows, "postgres"),
            ["INSERT INTO t (id, note, status) VALUES (1, 'ends with \\', 'old');"],
        )

    def test_key_predicates_escape_too(self):
        rows = [{"id": "a\\b", "v": 1}]
        self.assertEqual(
            self.mod.build_key_disjunction(["id"], rows, "mysql"),
            "(id = 'a\\\\b')",
        )


class WritePolicyTest(unittest.TestCase):
    """--allow-write must be gated by a declaration made outside this command line.

    The old code accepted `readonly: true` on an environment and still ran the
    UPDATE, so an environment could not be marked never-writable at all.
    """

    def make_fake_sq(self, tmpdir, count=1):
        fake = Path(tmpdir) / "fake-sq"
        fake.write_text(
            "#!/usr/bin/env python3\n"
            "import sys, json\n"
            "sql = sys.argv[-1] if len(sys.argv) > 1 else ''\n"
            f"print(json.dumps([{{'affected_rows': {count}}}]) if 'COUNT(*)' in sql else '[]')\n",
            encoding="utf-8",
        )
        fake.chmod(0o755)
        return fake

    def run_write(self, tmpdir, env=None, count=1, args=None,
                  sql="UPDATE cc_order SET status = 1 WHERE id = 1"):
        cmd = [
            str(DB_QUERY),
            "--sq-bin", str(self.make_fake_sq(tmpdir, count)),
            "--audit-log", str(Path(tmpdir) / "audit.log"),
        ]
        if env is not None:
            config = Path(tmpdir) / "connections.local.json"
            config.write_text(json.dumps({"environments": {"qa01": env}}), encoding="utf-8")
            cmd.extend(["--config", str(config), "--env", "qa01"])
        cmd.extend(args or [])
        cmd.extend(["--allow-write", "--sql", sql])
        return subprocess.run(cmd, text=True, capture_output=True, check=False)

    def test_configured_environment_refuses_writes_without_the_declaration(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_write(tmpdir, env={"source": "@qa01", "driver": "mysql"})

        self.assertEqual(result.returncode, 2)
        self.assertIn("is not writable", result.stderr)

    def test_readonly_true_no_longer_lets_a_write_through(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_write(
                tmpdir, env={"source": "@qa01", "driver": "mysql", "readonly": True}
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("is not writable", result.stderr)

    def test_declared_writable_environment_executes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_write(
                tmpdir, env={"source": "@qa01", "driver": "mysql", "writable": True}
            )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_ad_hoc_connection_refuses_writes_without_the_writable_flag(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_write(tmpdir, args=["--host", "db.internal", "--username", "u"])

        self.assertEqual(result.returncode, 2)
        self.assertIn("Ad-hoc connections are read-only", result.stderr)

    def test_ad_hoc_connection_executes_with_the_writable_flag(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_write(
                tmpdir, args=["--host", "db.internal", "--username", "u", "--writable"]
            )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_where_1_equals_1_is_caught_by_the_row_cap(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_write(
                tmpdir,
                env={"source": "@qa01", "driver": "mysql", "writable": True},
                count=50000,
                sql="UPDATE cc_order SET status = 1 WHERE 1=1",
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("would affect 50000 rows", result.stderr)
        self.assertIn("1000-row write cap", result.stderr)

    def test_max_write_rows_narrows_the_cap(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_write(
                tmpdir,
                env={"source": "@qa01", "driver": "mysql", "writable": True, "max_write_rows": 5},
                count=6,
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("would affect 6 rows", result.stderr)
        self.assertIn("5-row write cap", result.stderr)

    def test_write_at_the_cap_boundary_proceeds(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_write(
                tmpdir,
                env={"source": "@qa01", "driver": "mysql", "writable": True, "max_write_rows": 5},
                count=5,
            )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_where_confined_to_a_subquery_cannot_bound_the_write(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_write(
                tmpdir,
                env={"source": "@qa01", "driver": "mysql", "writable": True},
                sql="UPDATE cc_order SET status = (SELECT 1 FROM dual WHERE 1=1)",
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("top-level WHERE", result.stderr)

    def test_inserts_are_unaffected_by_the_row_cap(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_write(
                tmpdir,
                env={"source": "@qa01", "driver": "mysql", "writable": True},
                sql="INSERT INTO cc_order (id) VALUES (1)",
            )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_list_envs_reports_real_writability(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Path(tmpdir) / "connections.local.json"
            config.write_text(
                json.dumps(
                    {
                        "environments": {
                            "qa01": {"source": "@qa01", "driver": "mysql"},
                            "fix": {
                                "source": "@fix",
                                "driver": "mysql",
                                "writable": True,
                                "max_write_rows": 25,
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                [str(DB_QUERY), "--config", str(config), "--list-envs"],
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        summaries = {item["name"]: item for item in json.loads(result.stdout)["connections"]}
        self.assertFalse(summaries["qa01"]["writable"])
        self.assertTrue(summaries["fix"]["writable"])
        self.assertEqual(summaries["fix"]["max_write_rows"], 25)
        # The old summary claimed readonly:true on every connection, writable ones included.
        self.assertNotIn("readonly", summaries["fix"])


if __name__ == "__main__":
    unittest.main()
