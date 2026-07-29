import importlib.machinery
import importlib.util
import json
import os
import shlex
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MCP_SERVER = ROOT / "scripts" / "database-mcp"
MCP_SERVER_SOURCE = ROOT / "skills" / "database-cli" / "scripts" / "database-mcp"


def printed_sql(stdout):
    command = [line for line in stdout.splitlines() if line.startswith("sq ")][-1]
    return shlex.split(command)[-1]


class McpServerTest(unittest.TestCase):
    def call_server(self, messages):
        payload = "\n".join(json.dumps(message) for message in messages) + "\n"
        result = subprocess.run(
            [str(MCP_SERVER)],
            input=payload,
            text=True,
            capture_output=True,
            timeout=5,
        )
        if result.returncode != 0:
            sys.stderr.write(result.stderr)
        self.assertEqual(result.returncode, 0)
        return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]

    def write_config(self, tmpdir, data):
        config = Path(tmpdir) / "connections.local.json"
        config.write_text(json.dumps(data), encoding="utf-8")
        return config

    def test_initialize_and_lists_tools(self):
        responses = self.call_server(
            [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            ]
        )

        self.assertEqual(responses[0]["result"]["serverInfo"]["name"], "database-cli")
        tool_names = {tool["name"] for tool in responses[1]["result"]["tools"]}
        self.assertIn("list_envs", tool_names)
        self.assertIn("query_readonly", tool_names)
        self.assertIn("search_objects", tool_names)
        self.assertIn("add_connection", tool_names)
        self.assertIn("setup_status", tool_names)
        self.assertIn("execute_sql", tool_names)

        search_tool = next(tool for tool in responses[1]["result"]["tools"] if tool["name"] == "search_objects")
        object_types = search_tool["inputSchema"]["properties"]["object_type"]["enum"]
        self.assertIn("procedure", object_types)
        self.assertIn("function", object_types)
        self.assertIn("detail_level", search_tool["inputSchema"]["properties"])

        add_tool = next(tool for tool in responses[1]["result"]["tools"] if tool["name"] == "add_connection")
        self.assertIn("env", add_tool["inputSchema"]["required"])
        self.assertIn("driver", add_tool["inputSchema"]["properties"])
        self.assertIn("host", add_tool["inputSchema"]["properties"])
        self.assertIn("password_env", add_tool["inputSchema"]["properties"])

        status_tool = next(tool for tool in responses[1]["result"]["tools"] if tool["name"] == "setup_status")
        self.assertIn("sq_bin", status_tool["inputSchema"]["properties"])

        execute_tool = next(tool for tool in responses[1]["result"]["tools"] if tool["name"] == "execute_sql")
        self.assertEqual(execute_tool["inputSchema"]["required"], ["sql"])
        self.assertIn("url", execute_tool["inputSchema"]["properties"])
        self.assertIn("allow_write", execute_tool["inputSchema"]["properties"])

    def test_setup_status_returns_actionable_structured_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / "missing-connections.json"
            responses = self.call_server(
                [
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {
                            "name": "setup_status",
                            "arguments": {
                                "config": str(missing),
                                "sq_bin": "definitely-missing-sq-for-test",
                            },
                        },
                    }
                ]
            )

            result = responses[0]["result"]
            self.assertEqual(result["structuredContent"]["exit_code"], 0)
            data = result["structuredContent"]["json"]
            self.assertFalse(data["ready"])
            self.assertFalse(data["config"]["exists"])
            problem_codes = {problem["code"] for problem in data["problems"]}
            self.assertIn("missing_config", problem_codes)
            self.assertIn("missing_sq", problem_codes)
            self.assertTrue(any(action["command"] == "brew install sq" for action in data["next_actions"]))

    def test_add_connection_is_visible_without_restarting_server(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Path(tmpdir) / "connections.local.json"
            responses = self.call_server(
                [
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {
                            "name": "add_connection",
                            "arguments": {
                                "config": str(config),
                                "env": "qa02",
                                "driver": "mysql",
                                "host": "mysql-qa02.example.internal",
                                "username": "readonly_user",
                                "password_env": "QA02_DB_PASSWORD",
                                "display_name": "QNVIP QA02",
                                "environment": "qa02",
                                "project": "qnvip",
                                "description": "QA02 shared readonly connection.",
                                "aliases": ["qa-02", "test2"],
                                "max_rows": 50,
                            },
                        },
                    },
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {
                            "name": "list_envs",
                            "arguments": {"config": str(config)},
                        },
                    },
                ]
            )

            add_result = responses[0]["result"]
            self.assertEqual(add_result["structuredContent"]["exit_code"], 0)
            self.assertFalse(add_result["isError"])

            list_result = responses[1]["result"]["structuredContent"]
            data = list_result["json"]
            self.assertEqual(data["environments"], ["qa02"])
            self.assertEqual(data["connections"][0]["name"], "qa02")
            self.assertEqual(data["connections"][0]["display_name"], "QNVIP QA02")
            self.assertEqual(data["connections"][0]["aliases"], ["qa-02", "test2"])
            self.assertEqual(data["connections"][0]["max_rows"], 50)

    def test_add_connection_accepts_database_url_and_credentials(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = Path(tmpdir) / "connections.local.json"
            responses = self.call_server(
                [
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {
                            "name": "add_connection",
                            "arguments": {
                                "config": str(config),
                                "env": "qa03",
                                "url": "mysql://mysql-qa03.example.internal:3307/qnvip_center_order?charset=utf8mb4",
                                "username": "readonly_user",
                                "password": "local-secret",
                            },
                        },
                    }
                ]
            )

            result = responses[0]["result"]
            self.assertEqual(result["structuredContent"]["exit_code"], 0)
            data = json.loads(config.read_text(encoding="utf-8"))
            env = data["environments"]["qa03"]
            self.assertEqual(env["driver"], "mysql")
            self.assertEqual(env["host"], "mysql-qa03.example.internal")
            self.assertEqual(env["port"], 3307)
            self.assertEqual(env["database"], "qnvip_center_order")
            self.assertEqual(env["username"], "readonly_user")
            self.assertEqual(env["password"], "local-secret")
            self.assertEqual(env["params"], {"charset": "utf8mb4"})

    def test_tool_call_returns_structured_output(self):
        responses = self.call_server(
            [
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "check_sql",
                        "arguments": {"sql": "SELECT 1"},
                    },
                }
            ]
        )

        result = responses[0]["result"]
        self.assertIn("structuredContent", result)
        self.assertEqual(result["structuredContent"]["exit_code"], 0)
        self.assertEqual(result["structuredContent"]["stderr"], "")
        self.assertEqual(result["structuredContent"]["stdout"], "SELECT 1 LIMIT 200")
        self.assertEqual(result["content"][0]["text"], "SELECT 1 LIMIT 200")

    def test_execute_sql_supports_ad_hoc_write_with_explicit_allow_write(self):
        responses = self.call_server(
            [
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "execute_sql",
                        "arguments": {
                            "url": "mysql://mysql-adhoc.example.internal:3306/qnvip_center_order",
                            "username": "readonly_user",
                            "password": "local-secret",
                            "sql": "UPDATE cc_order SET status = 1 WHERE id = 10",
                            "allow_write": True,
                            "writable": True,
                            "print_command": True,
                        },
                    },
                }
            ]
        )

        result = responses[0]["result"]
        self.assertEqual(result["structuredContent"]["exit_code"], 0)
        stdout = result["structuredContent"]["stdout"]
        self.assertIn("@database_cli_adhoc", stdout)
        self.assertIn("UPDATE cc_order SET status = 1 WHERE id = 10", stdout)
        self.assertNotIn("local-secret", stdout)

    def test_execute_sql_refuses_ad_hoc_write_without_writable(self):
        """allow_write alone must not let an Agent write to a database it just described.

        Otherwise a protected environment could be re-specified as an ad-hoc
        connection, routing straight around its config entry.
        """
        responses = self.call_server(
            [
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "execute_sql",
                        "arguments": {
                            "url": "mysql://mysql-adhoc.example.internal:3306/qnvip_center_order",
                            "username": "readonly_user",
                            "sql": "UPDATE cc_order SET status = 1 WHERE id = 10",
                            "allow_write": True,
                            "print_command": True,
                        },
                    },
                }
            ]
        )

        result = responses[0]["result"]
        self.assertTrue(result["isError"])
        self.assertIn("Ad-hoc connections are read-only", result["structuredContent"]["stderr"])

    def test_preview_write_derives_readonly_selects(self):
        responses = self.call_server(
            [
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "preview_write",
                        "arguments": {
                            "url": "mysql://mysql-adhoc.example.internal:3306/qnvip_center_order",
                            "username": "readonly_user",
                            "password": "local-secret",
                            "sql": "DELETE FROM cc_order WHERE id = 10",
                            "print_command": True,
                        },
                    },
                }
            ]
        )

        result = responses[0]["result"]
        self.assertEqual(result["structuredContent"]["exit_code"], 0)
        stdout = result["structuredContent"]["stdout"]
        self.assertIn("SELECT COUNT(*) AS affected_rows FROM cc_order WHERE id = 10", stdout)
        self.assertIn("SELECT * FROM cc_order WHERE id = 10", stdout)
        self.assertNotIn("DELETE", stdout)
        self.assertNotIn("local-secret", stdout)

    def test_generate_rollback_passes_key_columns(self):
        responses = self.call_server(
            [
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "generate_rollback",
                        "arguments": {
                            "url": "mysql://mysql-adhoc.example.internal:3306/qnvip_center_order",
                            "username": "readonly_user",
                            "sql": "UPDATE cc_order SET status = 1 WHERE id = 10",
                            "key_columns": "id",
                            "print_command": True,
                        },
                    },
                }
            ]
        )

        result = responses[0]["result"]
        self.assertEqual(result["structuredContent"]["exit_code"], 0)
        stdout = result["structuredContent"]["stdout"]
        # print_command derives the read-only impact SELECTs, not the DML.
        self.assertIn("SELECT COUNT(*) AS affected_rows FROM cc_order WHERE id = 10", stdout)
        self.assertNotIn("UPDATE", stdout)

    def test_repair_defaults_to_readonly_without_allow_write(self):
        responses = self.call_server(
            [
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "repair",
                        "arguments": {
                            "url": "mysql://mysql-adhoc.example.internal:3306/qnvip_center_order",
                            "username": "readonly_user",
                            "sql": "DELETE FROM cc_order WHERE id = 7",
                            "print_command": True,
                        },
                    },
                }
            ]
        )

        result = responses[0]["result"]
        self.assertEqual(result["structuredContent"]["exit_code"], 0)
        stdout = result["structuredContent"]["stdout"]
        self.assertIn("SELECT COUNT(*) AS affected_rows FROM cc_order WHERE id = 7", stdout)
        self.assertIn("DELETE FROM cc_order WHERE id = 7", stdout)
        self.assertNotIn("--allow-write", stdout)

    def test_lists_configured_custom_tool(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = self.write_config(
                tmpdir,
                {
                    "environments": {
                        "qa01": {
                            "driver": "mysql",
                            "host": "mysql-qa01.example.internal",
                            "username": "readonly_user",
                        }
                    },
                    "tools": {
                        "find_order": {
                            "description": "Find one order by order number.",
                            "env": "qa01",
                            "sql": "SELECT id, order_no FROM cc_order WHERE order_no = :order_no",
                            "parameters": {
                                "order_no": {
                                    "type": "string",
                                    "description": "Order number.",
                                }
                            },
                        }
                    },
                },
            )

            responses = self.call_server(
                [
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/list",
                        "params": {"arguments": {"config": str(config)}},
                    }
                ]
            )

            tool_names = {tool["name"] for tool in responses[0]["result"]["tools"]}
            self.assertIn("find_order", tool_names)
            tool = next(tool for tool in responses[0]["result"]["tools"] if tool["name"] == "find_order")
            self.assertEqual(tool["inputSchema"]["required"], ["order_no"])

    def test_custom_tool_renders_readonly_sql_before_execution(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = self.write_config(
                tmpdir,
                {
                    "environments": {
                        "qa01": {
                            "driver": "mysql",
                            "host": "mysql-qa01.example.internal",
                            "username": "readonly_user",
                            "max_rows": 10,
                        }
                    },
                    "tools": {
                        "find_order": {
                            "description": "Find one order by order number.",
                            "env": "qa01",
                            "sql": "SELECT id, order_no FROM cc_order WHERE order_no = :order_no",
                            "parameters": {
                                "order_no": {
                                    "type": "string",
                                    "description": "Order number.",
                                }
                            },
                        }
                    },
                },
            )

            responses = self.call_server(
                [
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {
                            "name": "find_order",
                            "arguments": {
                                "config": str(config),
                                "order_no": "YP'001",
                                "_print_command": True,
                            },
                        },
                    }
                ]
            )

            result = responses[0]["result"]
            self.assertEqual(result["structuredContent"]["exit_code"], 0)
            sql = printed_sql(result["structuredContent"]["stdout"])
            self.assertIn("order_no = 'YP''001'", sql)
            self.assertIn("LIMIT 10", sql)

    def custom_tool_config(self, tmpdir, env):
        return self.write_config(
            tmpdir,
            {
                "environments": {"qa01": env},
                "tools": {
                    "find_order": {
                        "env": "qa01",
                        "sql": "SELECT id FROM cc_order WHERE order_no = :order_no",
                        "parameters": {"order_no": {"type": "string"}},
                    }
                },
            },
        )

    def call_find_order(self, config, order_no):
        responses = self.call_server(
            [
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "find_order",
                        "arguments": {
                            "config": str(config),
                            "order_no": order_no,
                            "_print_command": True,
                        },
                    },
                }
            ]
        )
        return responses[0]

    def test_custom_tool_escapes_a_backslash_parameter_for_mysql(self):
        """A trailing backslash would otherwise close the literal early on MySQL,
        letting the rest of the parameter parse as SQL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = self.custom_tool_config(
                tmpdir, {"driver": "mysql", "host": "h", "username": "readonly_user"}
            )
            result = self.call_find_order(config, "YP\\")["result"]

            self.assertEqual(result["structuredContent"]["exit_code"], 0)
            self.assertIn("order_no = 'YP\\\\'", printed_sql(result["structuredContent"]["stdout"]))

    def test_custom_tool_leaves_a_backslash_parameter_alone_for_postgres(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = self.custom_tool_config(
                tmpdir, {"driver": "postgres", "host": "h", "username": "readonly_user"}
            )
            result = self.call_find_order(config, "YP\\")["result"]

            self.assertEqual(result["structuredContent"]["exit_code"], 0)
            self.assertIn("order_no = 'YP\\'", printed_sql(result["structuredContent"]["stdout"]))

    def test_custom_tool_refuses_a_backslash_parameter_when_driver_is_unknown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = self.custom_tool_config(tmpdir, {"source": "@qa01"})
            # Custom-tool validation errors surface at the protocol level, the same
            # way a missing required parameter does.
            error = self.call_find_order(config, "YP\\")["error"]

            self.assertIn("without knowing the driver", error["message"])

    def test_custom_tool_resolves_the_driver_through_an_alias(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = self.write_config(
                tmpdir,
                {
                    "environments": {
                        "qa01": {
                            "driver": "mysql",
                            "host": "h",
                            "username": "readonly_user",
                            "aliases": ["qa-01"],
                        }
                    },
                    "tools": {
                        "find_order": {
                            "env": "qa-01",
                            "sql": "SELECT id FROM cc_order WHERE order_no = :order_no",
                            "parameters": {"order_no": {"type": "string"}},
                        }
                    },
                },
            )
            result = self.call_find_order(config, "YP\\")["result"]

            self.assertEqual(result["structuredContent"]["exit_code"], 0)
            self.assertIn("order_no = 'YP\\\\'", printed_sql(result["structuredContent"]["stdout"]))


class ConfigDiscoveryTest(unittest.TestCase):
    """The adapter must find config the same way db-query does.

    `$DATABASE_CLI_CONFIG` is documented as config source #2. The adapter's own
    reader used to ignore it and fall back to the default paths, so custom tools
    defined there never reached tools/list, and a session could have the CLI and
    the adapter reading two different files.
    """

    def write_config(self, tmpdir):
        config = Path(tmpdir) / "via-env.json"
        config.write_text(
            json.dumps(
                {
                    "environments": {"qa": {"driver": "mysql", "host": "h", "username": "u"}},
                    "tools": {
                        "find_order": {
                            "env": "qa",
                            "sql": "SELECT id FROM cc_order WHERE order_no = :order_no",
                            "parameters": {"order_no": {"type": "string"}},
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        return config

    def tool_names(self, env=None):
        payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}) + "\n"
        proc = subprocess.run(
            [str(MCP_SERVER)],
            input=payload,
            text=True,
            capture_output=True,
            timeout=10,
            env=env,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return {tool["name"] for tool in json.loads(proc.stdout)["result"]["tools"]}

    def test_custom_tools_are_discovered_through_the_config_env_var(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = self.write_config(tmpdir)
            env = {**os.environ, "DATABASE_CLI_CONFIG": str(config)}

            self.assertIn("find_order", self.tool_names(env=env))

    def test_explicit_config_still_wins_over_the_env_var(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = self.write_config(tmpdir)
            other = Path(tmpdir) / "other.json"
            other.write_text(json.dumps({"environments": {}}), encoding="utf-8")
            env = {**os.environ, "DATABASE_CLI_CONFIG": str(config)}

            payload = json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/list",
                    "params": {"arguments": {"config": str(other)}},
                }
            ) + "\n"
            proc = subprocess.run(
                [str(MCP_SERVER)], input=payload, text=True, capture_output=True, timeout=10, env=env
            )
            names = {tool["name"] for tool in json.loads(proc.stdout)["result"]["tools"]}

            self.assertNotIn("find_order", names)


class LiveMcpServerTest(unittest.TestCase):
    """Drive the server the way a real MCP host does: stdin stays open.

    McpServerTest pipes a payload and closes stdin, which a server that reads
    all of stdin before answering passes just fine. Every real stdio host holds
    the pipe open for the whole session, so only these tests prove the loop.
    """

    def start_server(self):
        proc = subprocess.Popen(
            [str(MCP_SERVER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.addCleanup(self.stop_server, proc)
        return proc

    def stop_server(self, proc):
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=5)
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            if stream is not None and not stream.closed:
                stream.close()

    def read_with_timeout(self, read_fn, timeout=5):
        box = {}

        def run():
            try:
                box["value"] = read_fn()
            except BaseException as exc:  # surfaced on the main thread below
                box["error"] = exc

        reader = threading.Thread(target=run, daemon=True)
        reader.start()
        reader.join(timeout)
        if reader.is_alive():
            self.fail(f"no response within {timeout}s while stdin stayed open")
        if "error" in box:
            raise box["error"]
        return box["value"]

    def send(self, proc, message):
        proc.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
        proc.stdin.flush()

    def read_json_line(self, proc, timeout=5):
        raw = self.read_with_timeout(proc.stdout.readline, timeout)
        return json.loads(raw.decode("utf-8"))

    def read_json_frame(self, proc, timeout=5):
        def read_frame():
            length = None
            while True:
                line = proc.stdout.readline()
                if not line or not line.strip():
                    break
                name, _, value = line.decode("ascii").partition(":")
                if name.lower() == "content-length":
                    length = int(value.strip())
            return proc.stdout.read(length)

        return json.loads(self.read_with_timeout(read_frame, timeout).decode("utf-8"))

    def test_responds_while_stdin_stays_open(self):
        proc = self.start_server()
        self.send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})

        response = self.read_json_line(proc)
        self.assertEqual(response["id"], 1)
        self.assertEqual(response["result"]["serverInfo"]["name"], "database-cli")

    def test_serves_successive_requests_on_one_connection(self):
        proc = self.start_server()
        self.send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        self.assertEqual(self.read_json_line(proc)["id"], 1)

        self.send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})

        response = self.read_json_line(proc)
        self.assertEqual(response["id"], 2, "the notification must not produce a reply")
        self.assertIn("query_readonly", {tool["name"] for tool in response["result"]["tools"]})

        proc.stdin.close()
        self.assertEqual(proc.wait(timeout=5), 0)

    def test_content_length_framing_on_a_live_stream(self):
        proc = self.start_server()
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        raw = body.encode("utf-8")
        proc.stdin.write(f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii") + raw)
        proc.stdin.flush()

        response = self.read_json_frame(proc)
        self.assertEqual(response["id"], 1)
        self.assertEqual(response["result"]["serverInfo"]["name"], "database-cli")

    def test_survives_a_malformed_message(self):
        proc = self.start_server()
        proc.stdin.write(b"{not json}\n")
        proc.stdin.flush()
        self.assertEqual(self.read_json_line(proc)["error"]["code"], -32700)

        self.send(proc, {"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {}})
        self.assertEqual(self.read_json_line(proc)["id"], 2)

    def test_survives_a_non_object_request(self):
        proc = self.start_server()
        self.send(proc, ["not", "an", "object"])
        self.assertEqual(self.read_json_line(proc)["error"]["code"], -32600)

        self.send(proc, {"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {}})
        self.assertEqual(self.read_json_line(proc)["id"], 2)


class SubprocessTimeoutTest(unittest.TestCase):
    """A wedged db-query must fail the call, not hold the session forever."""

    def load_server(self):
        loader = importlib.machinery.SourceFileLoader("database_mcp", str(MCP_SERVER_SOURCE))
        spec = importlib.util.spec_from_loader("database_mcp", loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module

    def stub_db_query(self, tmpdir, body):
        stub = Path(tmpdir) / "db-query"
        stub.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
        stub.chmod(0o755)
        return stub

    def test_hung_db_query_is_terminated_and_reported(self):
        module = self.load_server()
        with tempfile.TemporaryDirectory() as tmpdir:
            module.DB_QUERY = self.stub_db_query(tmpdir, "sleep 30")
            module.DB_QUERY_BACKSTOP = 1
            result = module.run_tool("query_readonly", {"env": "qa", "sql": "SELECT 1"})

        self.assertTrue(result["isError"])
        self.assertEqual(result["structuredContent"]["exit_code"], 124)
        self.assertIn("exceeded 1s", result["content"][0]["text"])

    def test_timeout_does_not_leak_the_password_from_the_command_line(self):
        module = self.load_server()
        with tempfile.TemporaryDirectory() as tmpdir:
            module.DB_QUERY = self.stub_db_query(tmpdir, "sleep 30")
            module.DB_QUERY_BACKSTOP = 1
            result = module.run_tool(
                "query_readonly",
                {"host": "db.internal", "username": "u", "password": "s3cret", "sql": "SELECT 1"},
            )

        self.assertNotIn("s3cret", json.dumps(result))

    def test_backstop_is_looser_than_the_timeout_handed_to_db_query(self):
        module = self.load_server()
        cmd = module.command_for_tool("query_readonly", {"env": "qa", "sql": "SELECT 1"})
        passed = int(cmd[cmd.index("--timeout") + 1])

        # db-query's own timeout must fire first: it knows which query stalled.
        self.assertLess(passed, module.DB_QUERY_BACKSTOP)
        self.assertGreaterEqual(
            module.DB_QUERY_BACKSTOP,
            passed * module.MAX_SQ_CALLS_PER_RUN,
            "backstop must cover a repair run's worth of sq invocations",
        )

    def test_db_query_accepts_the_timeout_flag_the_server_passes(self):
        cmd = [str(ROOT / "scripts" / "db-query"), "--timeout", "60", "--check-sql", "SELECT 1"]
        proc = subprocess.run(cmd, text=True, capture_output=True, timeout=10)
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
