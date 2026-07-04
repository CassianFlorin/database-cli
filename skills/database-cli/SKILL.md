---
name: database-cli
description: "Use when Codex needs to inspect database schema, search schema/table/column/index/procedure metadata, run safe SQL, compare records across environments, or produce/execute user-approved repair SQL through the database-cli local command-line workflow. MCP is only an optional adapter over the same CLI. This skill defaults to read-only safety; write SQL requires explicit user approval and --allow-write."
---

# Database CLI

Use this skill for database-backed investigation through the local database CLI workflow. Treat it as read-only by default. When invoked from the plugin root, the root `scripts/*` wrappers delegate to this skill's scripts. When installed directly under `~/.codex/skills/database-cli`, run scripts from that skill directory.

`database-cli` is CLI-first. `scripts/db-query` is the authoritative execution path for schema discovery, SQL safety checks, limits, ad-hoc connections, and repair-SQL evidence gathering. `scripts/database-mcp` is only an optional adapter for clients that need MCP tools; it must not become a separate query engine or product surface.

## Agent Quick Start

Use this path by default. It minimizes user prompts and keeps all DB access behind the safety wrapper.

1. Check whether the local setup is ready. This reads local config and `sq` availability only; it does not connect to a database:

```bash
scripts/db-query --setup-status
```

Read the JSON fields `ready`, `problems`, and `next_actions`. If `ready=false`, follow `next_actions` and ask the user only for the missing connection facts:

- environment name, such as `qa01` or `prod`
- database URL or host/domain
- username
- password environment variable, or a local password if the user explicitly prefers it
- optional display name, project, description, alias, and `max_rows`

2. Create or update the connection with the install entrypoint. This single command checks `sq` and writes config:

```bash
scripts/install \
  --env qa01 \
  --url "mysql://mysql-qa01.example.internal" \
  --username readonly_user \
  --password-env QA01_DB_PASSWORD \
  --non-interactive
```

Use `--config /path/to/connections.local.json` when the user wants a non-default config path. Use `--force` only when the user is updating an existing environment.

If the user gives connection details for one-off use, config is optional. Pass the user-provided facts directly:

```bash
scripts/db-query \
  --url "mysql://mysql-qa01.example.internal:3306/qnvip_center_commerce" \
  --username readonly_user \
  --password-env QA01_DB_PASSWORD \
  --sql "SELECT 1"
```

3. Verify with the cheapest safe calls:

```bash
scripts/db-query --setup-status
scripts/db-query --list-envs
scripts/db-query --env qa01 --sql "SELECT 1"
```

For production, run `SELECT 1` only after the user has agreed to a production connection check.

4. During investigation, discover metadata before data. Do not ask the user to choose a database/schema first:

```bash
scripts/db-query --env qa01 --search-objects "%order_no%" --object-type column --table cc_order
scripts/db-query --env qa01 --sql "SELECT id, order_no, status FROM qnvip_center_commerce.cc_order WHERE order_no = 'YP...'"
```

If a SQL statement is questionable, validate it without execution:

```bash
scripts/db-query --check-sql "SELECT id FROM cc_order WHERE order_no = 'YP...'"
```

## Hard Rules

- Confirm the target environment/connection before querying. If the environment is missing or ambiguous, list configured environments and connection metadata, then ask the user to choose.
- Do not require the user to preselect a database/schema. A configured environment represents a database server or account permission boundary, not one database. Search visible schema/table metadata first, then narrow with `--schema` only when needed.
- Default to read-only: `SELECT`, `SHOW`, `DESC`/`DESCRIBE`, `EXPLAIN`, and conservative read-only `WITH ... SELECT` queries.
- Execute write SQL only when the user explicitly asks/approves it in the current task, and only with `--allow-write` or MCP `allow_write=true`.
- With write approval, allow only DML starts: `INSERT`, `UPDATE`, `DELETE`, `REPLACE`.
- Approved `UPDATE` and `DELETE` statements must include `WHERE` and must be scoped to exact business keys or primary keys.
- Refuse DDL, permission, transaction, procedure, lock, export, or side-effect keywords even when writes are allowed.
- Keep queries scoped with exact business keys, selected columns, and a bounded result set.
- Use `scripts/db-query` rather than calling `sq` directly. The wrapper enforces read-only SQL checks and consistent output.
- If an Agent needs structured MCP tools, use `scripts/database-mcp`; it delegates to `scripts/db-query` and preserves the same safety boundary.
- Do not treat this project as a DBHub replacement or MCP platform. Prefer improving CLI and Skill workflow first; keep MCP thin.
- Treat configured `max_rows` as a hard result cap. Do not bypass it with larger `--limit` values.
- Treat `readonly=false` as invalid for this skill; it never enables write SQL.
- Configured MCP custom tools are allowed only for parameterized read-only SQL templates. Do not put repair SQL in a custom tool.
- If data must be repaired and the user has not explicitly allowed Agent execution, output SQL for a human to execute. Include target environment, pre-check SQL, change SQL, post-check SQL, and rollback or recovery notes.
- If the user explicitly allows Agent execution, run the pre-check first, execute exactly one DML statement with `--allow-write`, then run the post-check and report the affected evidence.

## Setup Check

Before the first query in a thread:

```bash
scripts/db-query --setup-status
```

Use the JSON `next_actions` as the default instruction path. If `sq` is missing, tell the user to install it with:

```bash
brew install sq
```

If no environments are configured, either ask for the connection facts needed by `scripts/install`, or use ad-hoc connection flags when the user already gave enough details for a one-off query. The minimum useful facts are database URL or host/domain, username, and password or `password_env`. The default local config path is `skills/database-cli/connections.local.json` when using the plugin root wrapper. Do not invent hosts, credentials, or environment mappings.

If the user is installing or adding a connection through an Agent and the connection details are missing, ask the user for the database URL or host, username, and either password or password environment variable. Do not guess connection URLs, usernames, passwords, or access scope.

For first-run setup after installing the Skill, use the install entrypoint. It can run interactively:

```bash
scripts/install
```

It can also configure a connection non-interactively:

```bash
scripts/install \
  --env qa01 \
  --url "mysql://mysql-qa01.example.internal" \
  --display-name "QNVIP QA01" \
  --environment qa01 \
  --project qnvip \
  --description "Shared QA readonly connection; search all visible schemas unless narrowed." \
  --alias qa-01 \
  --username readonly_user \
  --password-env QA01_DB_PASSWORD \
  --non-interactive
```

Standard Skill installation does not automatically run post-install hooks, so `scripts/install` is the required setup step. Prefer this command over separate dependency and config steps.

For config-only setup, use the initializer instead of hand-writing JSON:

```bash
scripts/init-config
```

The initializer accepts the same connection flags. Use it when `sq` has already been checked and only the config file must be changed:

```bash
scripts/init-config --env qa01 --url "mysql://mysql-qa01.example.internal" --username readonly_user --password-env QA01_DB_PASSWORD --non-interactive
```

`scripts/init-config --config /path/to/connections.local.json` is accepted as an alias for `--output`. Default database/schema is optional; the user can choose the concrete database/schema in SQL with fully-qualified names.

## Query Workflow

1. Identify the environment/connection and business keys from the user request. Treat configured aliases as valid environment names. If the user provides a URL/host and credentials directly, use ad-hoc flags instead of forcing config creation.
2. Check configured environments:

```bash
scripts/db-query --list-envs
```

3. For schema or table discovery, prefer metadata search first. Use inspect when the user needs a source/table overview:

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

Ad-hoc equivalent:

```bash
scripts/db-query --url "mysql://host/dbname" --username readonly_user --password-env DB_PASSWORD --sql "SELECT id FROM table_name WHERE id = 1"
```

6. Summarize only the fields needed to answer the user. Avoid spreading unrelated sensitive data.

7. When the user needs a data repair and has not explicitly approved Agent execution, do not execute it. Return a human-reviewed script package:

- target environment and connection name
- pre-check SQL and current evidence
- proposed change SQL
- post-check SQL
- rollback or recovery note
- explicit statement that database-cli did not execute the mutation

8. When the user explicitly approves Agent execution, execute only the approved DML:

```bash
scripts/db-query --env qa01 --allow-write --sql "UPDATE dbname.table_name SET status = 1 WHERE id = 10"
```

Run a pre-check before this command and a post-check after it.

## Optional MCP Adapter

When a client needs MCP tools, point it at:

```bash
scripts/database-mcp
```

The adapter exposes `setup_status`, `add_connection`, `list_envs`, `query_readonly`, `execute_sql`, `inspect`, `search_objects`, and `check_sql`. `setup_status` returns readiness, missing prerequisites, configured environments, and next actions without querying a database. `execute_sql` defaults to read-only and accepts ad-hoc connection fields; pass `allow_write=true` only after explicit user approval for DML. `add_connection` writes config through the same initializer path and lets a running Agent add or update a connection without restart; subsequent tool calls read the updated config. `search_objects` supports schema, table, column, index, procedure, and function metadata. Each `tools/call` keeps text `content` and also returns `structuredContent` with `exit_code`, `stdout`, `stderr`, and a `json` field when stdout is valid JSON. Use it only when Agent-native structured calls are useful; CLI remains the source of truth.

If `connections.local.json` has a top-level `tools` object, `scripts/database-mcp` also exposes those parameterized read-only custom tools. Parameters are rendered as SQL literals and then passed through `scripts/db-query`, so the same read-only validator and `max_rows` cap still apply.

## Useful Commands

Check Agent setup status without querying a database:

```bash
scripts/db-query --setup-status
```

Validate a SQL statement without executing it:

```bash
scripts/db-query --check-sql "SELECT * FROM cc_order WHERE order_no = 'YP...'"
```

Preview the command that would be executed:

```bash
scripts/db-query --env qa01 --sql "SELECT 1" --print-command
```

Use a one-off connection without writing config:

```bash
scripts/db-query --url "mysql://host/dbname" --username readonly_user --password-env DB_PASSWORD --sql "SELECT 1"
```

Execute approved DML:

```bash
scripts/db-query --env qa01 --allow-write --sql "UPDATE table_name SET status = 1 WHERE id = 10"
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

Create or update local config non-interactively through the install entrypoint:

```bash
scripts/install --env qa01 --url "mysql://mysql-qa01.example.internal" --username readonly_user --password-env QA01_DB_PASSWORD --non-interactive
```

## Notes

- Direct config is preferred: the wrapper can build a temporary `sq` source from `driver`, `host`, `port`, `username`, and `password`. `database` and `schema` are optional defaults, not access limits.
- `sq sql` accepts a single SQL statement and supports JSON, CSV, Markdown, YAML, and text output.
- `sq inspect --json` can inspect source metadata, tables, and columns.
- Keep source handles and credentials in local config. Do not commit secrets to this skill.
