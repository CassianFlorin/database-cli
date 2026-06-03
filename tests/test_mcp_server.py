import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MCP_SERVER = ROOT / "scripts" / "database-mcp"


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


if __name__ == "__main__":
    unittest.main()
