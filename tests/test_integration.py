"""End-to-end tests against a real `sq` and a real SQLite database.

Every other test in this suite stubs `sq`, so nothing checked that the command
database-cli builds is one `sq` actually accepts, nor that generated rollback
SQL parses and restores values on a real engine. These do, with no server to
stand up: SQLite is just a file.

Skipped when `sq` is not installed, so a contributor without it still gets a
green run; CI installs it so the coverage is not silently lost.
"""

import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB_QUERY = ROOT / "scripts" / "db-query"
MCP_SERVER = ROOT / "scripts" / "database-mcp"
SQ = shutil.which("sq")


class SqAvailabilityTest(unittest.TestCase):
    def test_sq_is_present_when_required(self):
        """CI sets DATABASE_CLI_REQUIRE_SQ=1 so a broken sq install fails the
        build rather than skipping every integration test in silence."""
        if os.environ.get("DATABASE_CLI_REQUIRE_SQ") != "1":
            self.skipTest("sq is optional in this environment")
        self.assertIsNotNone(SQ, "DATABASE_CLI_REQUIRE_SQ=1 but sq is not on PATH")

SEED = [
    (1, "YP'001", 0, "plain"),          # a quote, which every dialect doubles
    (2, "YP002", 0, r"C:\Users\admin"), # a backslash, which dialects disagree on
    (3, "YP003", 1, None),              # NULL, which must not become 'None'
    (4, "YP004", 1, "tail"),
]


@unittest.skipUnless(SQ, "sq is not installed")
class SqliteIntegrationTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.db = self.tmp / "cc.db"
        conn = sqlite3.connect(self.db)
        conn.execute(
            "CREATE TABLE cc_order "
            "(id INTEGER PRIMARY KEY, order_no TEXT, status INTEGER, note TEXT)"
        )
        conn.executemany("INSERT INTO cc_order VALUES (?,?,?,?)", SEED)
        conn.commit()
        conn.close()

    # --- helpers -----------------------------------------------------------

    def db_query(self, *args, stdin=subprocess.DEVNULL, check=True):
        proc = subprocess.run(
            [str(DB_QUERY), "--driver", "sqlite3", "--path", str(self.db), "--no-audit", *args],
            text=True,
            capture_output=True,
            stdin=stdin,
            timeout=90,
        )
        if check:
            self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc

    def config_with(self, **env_extra):
        env = {"driver": "sqlite3", "path": str(self.db)}
        env.update(env_extra)
        config = self.tmp / "connections.local.json"
        config.write_text(json.dumps({"environments": {"local": env}}), encoding="utf-8")
        return config

    def configured_query(self, config, *args, check=True):
        proc = subprocess.run(
            [str(DB_QUERY), "--config", str(config), "--env", "local", "--no-audit", *args],
            text=True,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=90,
        )
        if check:
            self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc

    def query(self, sql, *args):
        return json.loads(self.db_query("--sql", sql, *args).stdout)

    def table(self):
        return self.query("SELECT id, order_no, status, note FROM cc_order ORDER BY id")

    # --- reads -------------------------------------------------------------

    def test_read_query_returns_rows_from_a_real_database(self):
        self.assertEqual(
            self.table(),
            [
                {"id": 1, "order_no": "YP'001", "status": 0, "note": "plain"},
                {"id": 2, "order_no": "YP002", "status": 0, "note": "C:\\Users\\admin"},
                {"id": 3, "order_no": "YP003", "status": 1, "note": None},
                {"id": 4, "order_no": "YP004", "status": 1, "note": "tail"},
            ],
        )

    def test_auto_appended_limit_is_one_the_engine_accepts(self):
        rows = self.query("SELECT id FROM cc_order ORDER BY id", "--limit", "2")

        self.assertEqual(rows, [{"id": 1}, {"id": 2}])

    def test_max_rows_caps_a_larger_explicit_limit(self):
        rows = self.query("SELECT id FROM cc_order ORDER BY id LIMIT 100", "--max-rows", "2")

        self.assertEqual(len(rows), 2)

    def test_inspect_describes_the_table(self):
        data = json.loads(self.db_query("--inspect", "cc_order").stdout)

        self.assertEqual(data["name"], "cc_order")
        self.assertEqual(data["row_count"], len(SEED))
        self.assertIn("order_no", {column["name"] for column in data["columns"]})

    def test_show_create_table_reaches_the_engine(self):
        # The keyword allowlist used to reject this before it ever ran.
        rows = self.query("SELECT sql FROM sqlite_master WHERE name = 'cc_order'")

        self.assertIn("cc_order", rows[0]["sql"])

    # --- stdin isolation ---------------------------------------------------

    def test_a_pipe_on_stdin_does_not_reach_sq(self):
        """sq reads stdin as query input when it is not a terminal.

        db-query used to let it inherit the caller's stdin, so any caller
        holding an open pipe -- the MCP adapter, a CI harness -- made sq block
        on it until the timeout fired.
        """
        proc = subprocess.Popen(
            [str(DB_QUERY), "--driver", "sqlite3", "--path", str(self.db), "--no-audit",
             "--sql", "SELECT id FROM cc_order ORDER BY id LIMIT 1"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        # Deliberately never write and never close: an inherited pipe would hang.
        stdout, stderr = proc.communicate(timeout=30)

        self.assertEqual(proc.returncode, 0, stderr)
        self.assertEqual(json.loads(stdout), [{"id": 1}])

    # --- write preview and rollback ---------------------------------------

    def test_preview_write_counts_without_changing_anything(self):
        before = self.table()
        envelope = json.loads(
            self.db_query("--preview-write", "UPDATE cc_order SET status = 9 WHERE status = 0").stdout
        )

        self.assertEqual(envelope["affected_rows"], 2)
        self.assertEqual([row["id"] for row in envelope["snapshot"]], [1, 2])
        self.assertEqual(self.table(), before)

    def test_generated_update_rollback_restores_values_exactly(self):
        before = self.table()
        package = json.loads(
            self.db_query(
                "--writable", "--allow-write", "--key-columns", "id",
                "--repair", "UPDATE cc_order SET note = 'CHANGED' WHERE status = 0",
            ).stdout
        )
        self.assertTrue(package["executed"])
        self.assertNotEqual(self.table(), before)

        for statement in package["rollback_sql"]:
            self.db_query("--writable", "--allow-write", "--sql", statement.rstrip(";"))

        # Includes the backslash and quote rows: the rollback SQL has to parse
        # on the engine and restore the original bytes, not an approximation.
        self.assertEqual(self.table(), before)

    def test_generated_delete_rollback_reinserts_the_rows(self):
        before = self.table()
        package = json.loads(
            self.db_query("--generate-rollback", "DELETE FROM cc_order WHERE id IN (2, 3)").stdout
        )
        self.assertFalse(package["executed"])

        self.db_query("--writable", "--allow-write", "--sql", "DELETE FROM cc_order WHERE id IN (2, 3)")
        self.assertEqual(len(self.table()), len(SEED) - 2)

        for statement in package["rollback_sql"]:
            self.db_query("--writable", "--allow-write", "--sql", statement.rstrip(";"))

        self.assertEqual(self.table(), before)

    def test_repair_executes_and_post_checks(self):
        package = json.loads(
            self.db_query(
                "--writable", "--allow-write", "--key-columns", "id",
                "--repair", "UPDATE cc_order SET status = 5 WHERE id = 4",
            ).stdout
        )

        self.assertTrue(package["executed"])
        self.assertEqual(package["change_result"]["exit_code"], 0)
        self.assertEqual(package["post_check"]["exit_code"], 0)
        self.assertEqual(package["post_check"]["rows"][0]["status"], 5)

    def test_repair_without_allow_write_changes_nothing(self):
        before = self.table()
        package = json.loads(
            self.db_query(
                "--key-columns", "id",
                "--repair", "UPDATE cc_order SET status = 5 WHERE id = 4",
            ).stdout
        )

        self.assertFalse(package["executed"])
        self.assertEqual(self.table(), before)

    # --- write policy against real counts ----------------------------------

    def test_write_row_cap_uses_the_real_affected_count(self):
        config = self.config_with(writable=True, max_write_rows=1)
        proc = self.configured_query(
            config, "--allow-write", "--sql", "UPDATE cc_order SET status = 7 WHERE status = 0",
            check=False,
        )

        self.assertEqual(proc.returncode, 2)
        self.assertIn("would affect 2 rows", proc.stderr)
        self.assertIn("1-row write cap", proc.stderr)
        self.assertEqual([row["status"] for row in self.table()], [0, 0, 1, 1])

    def test_write_within_the_cap_reaches_the_engine(self):
        config = self.config_with(writable=True, max_write_rows=2)
        self.configured_query(
            config, "--allow-write", "--sql", "UPDATE cc_order SET status = 7 WHERE status = 0"
        )

        self.assertEqual([row["status"] for row in self.table()], [7, 7, 1, 1])

    def test_non_writable_environment_refuses_before_touching_the_engine(self):
        config = self.config_with()
        proc = self.configured_query(
            config, "--allow-write", "--sql", "UPDATE cc_order SET status = 7 WHERE id = 1",
            check=False,
        )

        self.assertEqual(proc.returncode, 2)
        self.assertIn("is not writable", proc.stderr)
        self.assertEqual(self.table()[0]["status"], 0)


@unittest.skipUnless(SQ, "sq is not installed")
class McpIntegrationTest(unittest.TestCase):
    """The adapter has to work against a real engine over a live connection.

    Both halves matter: the server must answer while stdin stays open, and the
    db-query it spawns must not inherit that same pipe.
    """

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Path(tmp.name) / "cc.db"
        conn = sqlite3.connect(self.db)
        conn.execute("CREATE TABLE cc_order (id INTEGER PRIMARY KEY, order_no TEXT)")
        conn.executemany("INSERT INTO cc_order VALUES (?,?)", [(1, "YP'001"), (2, "YP002")])
        conn.commit()
        conn.close()

        self.proc = subprocess.Popen(
            [str(MCP_SERVER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self.addCleanup(self.stop)

    def stop(self):
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait(timeout=10)
        for stream in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
            if stream is not None and not stream.closed:
                stream.close()

    def call(self, name, arguments):
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        self.proc.stdin.write(json.dumps(request) + "\n")
        self.proc.stdin.flush()
        return json.loads(self.proc.stdout.readline())["result"]

    def test_query_returns_rows_while_the_client_pipe_stays_open(self):
        result = self.call(
            "query_readonly",
            {"driver": "sqlite3", "path": str(self.db),
             "sql": "SELECT id, order_no FROM cc_order ORDER BY id"},
        )

        self.assertFalse(result["isError"], result["structuredContent"]["stderr"])
        self.assertEqual(
            result["structuredContent"]["json"],
            [{"id": 1, "order_no": "YP'001"}, {"id": 2, "order_no": "YP002"}],
        )

    def test_successive_queries_share_one_connection(self):
        first = self.call("query_readonly", {"driver": "sqlite3", "path": str(self.db),
                                             "sql": "SELECT COUNT(*) AS n FROM cc_order"})
        self.assertEqual(first["structuredContent"]["json"][0]["n"], 2)

        second = self.call("inspect", {"driver": "sqlite3", "path": str(self.db),
                                       "target": "cc_order"})
        self.assertFalse(second["isError"], second["structuredContent"]["stderr"])
        self.assertEqual(second["structuredContent"]["json"]["name"], "cc_order")


if __name__ == "__main__":
    unittest.main()
