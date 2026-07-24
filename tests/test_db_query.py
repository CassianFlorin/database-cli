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
        fake.write_text("#!/usr/bin/env python3\nprint('[]')\n", encoding="utf-8")
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

    def run_repair(self, tmpdir, dml, rows, count=None, extra=None):
        config = self.write_config(tmpdir, {"source": "@qa01", "driver": "mysql"})
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


if __name__ == "__main__":
    unittest.main()
