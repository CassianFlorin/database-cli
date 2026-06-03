---
name: database-cli
description: "Use when Codex needs to inspect database schema, search schema/table/column/index/procedure metadata, run safe read-only SQL, compare records across environments, or produce human-reviewed repair SQL through the database-cli local command-line workflow. MCP is only an optional adapter over the same CLI. This skill enforces read-only safety: never mutate database data directly; output repair SQL for humans to execute when changes are required."
---

# Database CLI

Use this skill for database-backed investigation through the local database CLI workflow. Treat it as a read-only evidence tool. When invoked from the plugin root, the root `scripts/*` wrappers delegate to this skill's scripts. When installed directly under `~/.codex/skills/database-cli`, run scripts from that skill directory.

`database-cli` is CLI-first. `scripts/db-query` is the authoritative execution path for schema discovery, read-only SQL, safety checks, limits, and repair-SQL evidence gathering. `scripts/database-mcp` is only an optional adapter for clients that need MCP tools; it must not become a separate query engine or product surface.

## Hard Rules

- Confirm the target environment/connection before querying. If the environment is missing or ambiguous, list configured environments and connection metadata, then ask the user to choose.
- Do not require the user to preselect a database/schema. A configured environment represents a database server or account permission boundary, not one database. Search visible schema/table metadata first, then narrow with `--schema` only when needed.
- Never execute database mutations through this skill in any environment.
- Allow only `SELECT`, `SHOW`, `DESC`/`DESCRIBE`, `EXPLAIN`, and conservative read-only `WITH ... SELECT` queries.
- Refuse SQL containing mutation, DDL, permission, transaction, procedure, lock, export, or side-effect keywords.
- Keep queries scoped with exact business keys, selected columns, and a bounded result set.
- Use `scripts/db-query` rather than calling `sq` directly. The wrapper enforces read-only SQL checks and consistent output.
- If an Agent needs structured MCP tools, use `scripts/database-mcp`; it delegates to `scripts/db-query` and preserves the same safety boundary.
- Do not treat this project as a DBHub replacement or MCP platform. Prefer improving CLI and Skill workflow first; keep MCP thin.
- Treat configured `max_rows` as a hard result cap. Do not bypass it with larger `--limit` values.
- Treat `readonly=false` as invalid for this skill; it never enables write SQL.
- Configured MCP custom tools are allowed only for parameterized read-only SQL templates. Do not put repair SQL in a custom tool.
- If data must be repaired, output SQL for a human to execute. Include target environment, pre-check SQL, change SQL, post-check SQL, and rollback or recovery notes.

## Setup Check

Before the first query in a thread:

```bash
command -v sq
scripts/db-query --list-envs
```

If `sq` is missing, tell the user to install it with:

```bash
brew install sq
```

If no environments are configured, read `references/config.md` and ask the user to create a local `connections.local.json` with database server address/domain, optional port, username, and password or `password_env`. The default local config path is `skills/database-cli/connections.local.json` when using the plugin root wrapper. Do not invent hosts, credentials, or environment mappings.

If the user is installing or adding a connection through an Agent and the connection details are missing, ask the user for the database URL or host, username, and either password or password environment variable. Do not guess connection URLs, usernames, passwords, or access scope.

For first-run setup after installing the Skill, use the install entrypoint:

```bash
scripts/install
```

It checks for `sq` and then asks the user for database connection details. Standard Skill installation does not automatically run post-install hooks, so this command is the required setup step.

For config-only setup, use the initializer instead of hand-writing JSON:

```bash
scripts/init-config
```

The initializer also accepts a user-provided database URL:

```bash
scripts/init-config --env qa01 --url "mysql://mysql-qa01.example.internal" --username readonly_user --password-env QA01_DB_PASSWORD
```

The initializer prompts for database server address/domain, optional port, username, and password storage. Default database/schema is optional; the user can choose the concrete database/schema in SQL with fully-qualified names.

## Query Workflow

1. Identify the environment/connection and business keys from the user request. Treat configured aliases as valid environment names.
2. Check configured environments:

```bash
scripts/db-query --list-envs
```

3. For schema or table discovery, prefer:

```bash
scripts/db-query --env qa01 --inspect
scripts/db-query --env qa01 --inspect table_name
```

4. For object metadata search, do not ask for a database first. Search all schemas visible to the configured account:

```bash
scripts/db-query --env qa01 --search-objects "%cc_order%" --object-type table
scripts/db-query --env qa01 --search-objects "%order_no%" --object-type column --table cc_order
scripts/db-query --env qa01 --search-objects "%idx_order%" --object-type index --table cc_order
scripts/db-query --env qa01 --search-objects "%sync_order%" --object-type procedure
scripts/db-query --env qa01 --search-objects "%calc%" --object-type function --detail-level full
```

If results are too broad, then narrow with `--schema`:

```bash
scripts/db-query --env qa01 --schema qnvip_center_commerce --search-objects "%order_no%" --object-type column
```

Use `--detail-level names` for quick discovery, `--detail-level summary` for normal investigation, and `--detail-level full` when comments, routine definitions, or index details matter.

5. For data lookup, run a bounded read-only query:

```bash
scripts/db-query --env qa01 --sql "SELECT id, order_no, status FROM dbname.schema_or_table WHERE order_no = 'YP...'"
```

6. Summarize only the fields needed to answer the user. Avoid spreading unrelated sensitive data.

## Optional MCP Adapter

When a client needs MCP tools, point it at:

```bash
scripts/database-mcp
```

The adapter exposes `add_connection`, `list_envs`, `query_readonly`, `inspect`, `search_objects`, and `check_sql`. `add_connection` writes config through the same initializer path and lets a running Agent add or update a connection without restart; subsequent tool calls read the updated config. `search_objects` supports schema, table, column, index, procedure, and function metadata. Each `tools/call` keeps text `content` and also returns `structuredContent` with `exit_code`, `stdout`, `stderr`, and a `json` field when stdout is valid JSON. Use it only when Agent-native structured calls are useful; CLI remains the source of truth.

If `connections.local.json` has a top-level `tools` object, `scripts/database-mcp` also exposes those parameterized read-only custom tools. Parameters are rendered as SQL literals and then passed through `scripts/db-query`, so the same read-only validator and `max_rows` cap still apply.

## Useful Commands

Validate a SQL statement without executing it:

```bash
scripts/db-query --check-sql "SELECT * FROM cc_order WHERE order_no = 'YP...'"
```

Preview the command that would be executed:

```bash
scripts/db-query --env qa01 --sql "SELECT 1" --print-command
```

Choose a non-default output format:

```bash
scripts/db-query --env qa01 --format markdown --sql "SHOW TABLES"
```

Search table, column, or index metadata:

```bash
scripts/db-query --env qa01 --search-objects "%order_no%" --object-type column --table cc_order
```

Use a specific config file:

```bash
DATABASE_CLI_CONFIG=/path/to/connections.json scripts/db-query --list-envs
```

Create or update local config non-interactively:

```bash
scripts/init-config --env qa01 --url "mysql://mysql-qa01.example.internal" --username readonly_user --password-env QA01_DB_PASSWORD
```

## Notes

- Direct config is preferred: the wrapper can build a temporary `sq` source from `driver`, `host`, `port`, `username`, and `password`. `database` and `schema` are optional defaults, not access limits.
- `sq sql` accepts a single SQL statement and supports JSON, CSV, Markdown, YAML, and text output.
- `sq inspect --json` can inspect source metadata, tables, and columns.
- Keep source handles and credentials in local config. Do not commit secrets to this skill.
