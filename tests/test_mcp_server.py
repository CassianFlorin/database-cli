import json
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MCP_SERVER = ROOT / "scripts" / "database-mcp"


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

        search_tool = next(tool for tool in responses[1]["result"]["tools"] if tool["name"] == "search_objects")
        object_types = search_tool["inputSchema"]["properties"]["object_type"]["enum"]
        self.assertIn("procedure", object_types)
        self.assertIn("function", object_types)
        self.assertIn("detail_level", search_tool["inputSchema"]["properties"])

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


if __name__ == "__main__":
    unittest.main()
