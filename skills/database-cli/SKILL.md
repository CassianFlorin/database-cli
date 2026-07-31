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
- Default to read-only: `SELECT`, `SHOW`, `DESC`/`DESCRIBE`, `EXPLAIN`, and conservative read-only `WITH ... SELECT` queries. `SHOW CREATE TABLE`, `SHOW GRANTS`, and the other `SHOW` forms that name a reserved word are read-only and accepted.
- `EXPLAIN ANALYZE` over `INSERT`/`UPDATE`/`DELETE`/`REPLACE` is always refused, including with `--allow-write`: MySQL 8.0.18+ executes the statement for real, and an `EXPLAIN` bypasses every guard that keys off the first token (the `WHERE` requirement, the affected-row cap, and the audit read/write split). `EXPLAIN ANALYZE SELECT` is fine.
- Execute write SQL only when the user explicitly asks/approves it in the current task, and only with `--allow-write` or MCP `allow_write=true`.
- With write approval, allow only DML starts: `INSERT`, `UPDATE`, `DELETE`, `REPLACE`.
- Approved `UPDATE` and `DELETE` statements must include `WHERE` and must be scoped to exact business keys or primary keys.
- Refuse DDL, permission, transaction, procedure, lock, export, or side-effect keywords even when writes are allowed.
- Keep queries scoped with exact business keys, selected columns, and a bounded result set.
- Use `scripts/db-query` rather than calling `sq` directly. The wrapper enforces read-only SQL checks and consistent output.
- If an Agent needs structured MCP tools, use `scripts/database-mcp`; it delegates to `scripts/db-query` and preserves the same safety boundary.
- Do not treat this project as a DBHub replacement or MCP platform. Prefer improving CLI and Skill workflow first; keep MCP thin.
- Treat configured `max_rows` as a hard result cap. Do not bypass it with larger `--limit` values.
- `--allow-write` alone is never enough. A configured environment must declare `"writable": true` in the config file; without it the environment refuses DML, and that refusal is not something a tool call can override. Ask the user to add the flag to their config rather than working around it.
- Ad-hoc (`--url`/`--host`) connections additionally require `--writable` (MCP `writable: true`) next to `--allow-write`. Never re-describe a configured environment as an ad-hoc connection to get around its config entry; if an environment is not writable, that is the answer.
- Approved `UPDATE`/`DELETE` are counted before they run and refused above `max_write_rows` (default 1000). A refusal means the statement's real scope is wider than intended — treat it as a stop condition and narrow the `WHERE` clause, not as a cap to raise.
- Treat `readonly=false` as invalid for this skill; it is rejected outright. Use `"writable": true` to grant DML instead.
- Configured MCP custom tools are allowed only for parameterized read-only SQL templates. Do not put repair SQL in a custom tool.
- If data must be repaired and the user has not explicitly allowed Agent execution, output SQL for a human to execute. Include target environment, pre-check SQL, change SQL, post-check SQL, and rollback or recovery notes. Prefer `--generate-rollback` over hand-writing the reverse SQL.
- If the user explicitly allows Agent execution, run the pre-check first, execute exactly one DML statement with `--allow-write`, then run the post-check and report the affected evidence.
- Before proposing or executing any `UPDATE`/`DELETE`, run `--preview-write` first and confirm the affected-row count matches the intended scope. Treat an unexpected count as a stop condition, not a detail.

## Setup Check

Before the first query in a thread:

```bash
scripts/db-query --setup-status
```

Use the JSON `next_actions` as the default instruction path. If `sq` is missing, tell the user to install it with:

```bash
brew install sq
```

If no environments are configured, either ask for the connection facts needed by `scripts/install`, or use ad-hoc connection flags when the user already gave enough details for a one-off query. The minimum useful facts are database URL or host/domain, username, and password or `password_env`. The default config path is `~/.config/database-cli/connections.json`, outside the repository; an existing `skills/database-cli/connections.local.json` is still used and still takes read precedence, so relocating one means moving the file, not copying it. Do not invent hosts, credentials, or environment mappings.

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

7. When the user needs a data repair and has not explicitly approved Agent execution, do not execute it. Prefer `--repair` (without `--allow-write`) to assemble the human-reviewed package in one call; it returns the target environment, pre-check evidence, change SQL, rollback SQL, post-check SQL, and an explicit not-executed note. Otherwise return the same package:

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

## Preview Write Impact

Before proposing or running any `UPDATE`/`DELETE`, preview its blast radius. `--preview-write` never executes the statement; it derives a read-only `SELECT COUNT(*)` plus a bounded before-snapshot from the statement's own `FROM`/`WHERE`, so it needs no `--allow-write`:

```bash
scripts/db-query --env qa01 --preview-write "UPDATE cc_order SET status = 1 WHERE order_no = 'YP...'"
```

It prints one JSON object: `affected_rows` (exact count), `snapshot` (the matched rows before any change, capped by `max_rows`), `snapshot_truncated`, and the derived `count_sql`/`snapshot_sql`. The `WHERE` target is extracted at top-level parenthesis depth, so a subquery's inner `WHERE` never becomes the boundary. Use this as the pre-check evidence in a repair package, and to confirm the affected-row count matches the user's intent before asking for write approval. Only single-statement `UPDATE`/`DELETE` with a `WHERE` clause are supported; `INSERT`/`REPLACE` have no before-image and are rejected.

## Generate Rollback

`--generate-rollback` produces — but never executes — the SQL that would undo an `UPDATE`/`DELETE`, built from the current before-image. It only runs read-only SELECTs; the rollback is output for a human to review and run.

String values are quoted for the environment's `driver`, because MySQL, MariaDB, and ClickHouse read a backslash inside a literal as an escape while the other drivers read it literally. If an environment has no `driver` (a `source`-only entry), a value containing a backslash is refused rather than quoted the wrong way — add `driver` to the config instead of hand-editing the emitted SQL. Values that have no faithful literal form (`NaN`, `Infinity`) are refused for the same reason: a rollback that silently restores something else is worse than no rollback.

```bash
scripts/db-query --env qa01 --generate-rollback "UPDATE cc_order SET status = 1 WHERE id = 10" --key-columns id
scripts/db-query --env qa01 --generate-rollback "DELETE FROM cc_order WHERE id = 10"
```

- `UPDATE` rollback restores each changed column to its captured old value, scoped by `--key-columns` (comma-separated). Key columns are required for `UPDATE` so each restore statement targets exact rows; the Agent knows them from prior schema discovery.
- `DELETE` rollback re-inserts each captured row with all its columns.

The output JSON includes `rollback_sql` (a list of statements), `executed: false`, `table`, `key_columns`, `set_columns`, `affected_rows`, and the `snapshot`. Guards:

- The target must be a single, unaliased table. JOINs, aliases, comma-lists, and subquery sources are rejected because the rollback target would be ambiguous.
- If the matched-row count exceeds the captured snapshot (the `max_rows` cap), rollback is **refused** — a partial rollback is more dangerous than none. Narrow the `WHERE` clause or raise `max_rows`.
- Generated values are a best-effort literal encoding of the snapshot (NULL, numbers, quoted/escaped strings). Dates, decimals-as-strings, and binary types may need manual review before running.

Use this to produce the rollback section of a repair package instead of hand-writing reverse SQL.

## Repair Package

`--repair` orchestrates the pieces above into one command: pre-check, change, rollback (from the same before-image), and post-check. It is read-only by default and prints a complete package for a human to review:

```bash
scripts/db-query --env qa01 --repair "UPDATE cc_order SET status = 1 WHERE id = 10" --key-columns id
```

The JSON package contains `pre_check` (affected-row snapshot), `change_sql`, `rollback_sql`, `post_check_sql`, and `executed: false`. For `UPDATE` the post-check re-selects the exact affected rows by key so their new values are visible; for `DELETE` it counts remaining matches (expected 0). This is the human-reviewed script package the Hard Rules require.

With explicit user approval, add `--allow-write` to execute the change and run the post-check in one step:

```bash
scripts/db-query --env qa01 --allow-write --repair "UPDATE cc_order SET status = 1 WHERE id = 10" --key-columns id
```

The executed package adds `executed: true`, `change_result` (exit code and driver output), and `post_check` (the after-state rows). The before-image and rollback are captured immediately before the change, so `rollback_sql` matches exactly what was changed. Guards match `--generate-rollback`: single unaliased table, `--key-columns` required for `UPDATE`, and refusal when the matched rows exceed the snapshot cap.

This flow is not transactionally atomic — database-cli runs one statement at a time and does not open a transaction — so a concurrent change between the pre-check and the write is possible. Keep the returned `rollback_sql` until the post-check confirms the intended result.

## Optional MCP Adapter

When a client needs MCP tools, point it at:

```bash
scripts/database-mcp
```

The adapter exposes `setup_status`, `add_connection`, `list_envs`, `query_readonly`, `execute_sql`, `preview_write`, `generate_rollback`, `repair`, `inspect`, `search_objects`, and `check_sql`. `preview_write` reports an UPDATE/DELETE's affected-row count and a bounded before-snapshot without executing it; `generate_rollback` emits (never executes) the reverse SQL from the before-image; `repair` assembles the full pre-check/change/rollback/post-check package and executes only when `allow_write=true`. `preview_write` and `generate_rollback` need no `allow_write`. `setup_status` returns readiness, missing prerequisites, configured environments, and next actions without querying a database. `execute_sql` defaults to read-only and accepts ad-hoc connection fields; pass `allow_write=true` only after explicit user approval for DML. `add_connection` writes config through the same initializer path and lets a running Agent add or update a connection without restart; subsequent tool calls read the updated config. `search_objects` supports schema, table, column, index, procedure, and function metadata. Each `tools/call` keeps text `content` and also returns `structuredContent` with `exit_code`, `stdout`, `stderr`, and a `json` field when stdout is valid JSON. Use it only when Agent-native structured calls are useful; CLI remains the source of truth.

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

Preview an UPDATE/DELETE's impact without executing it:

```bash
scripts/db-query --env qa01 --preview-write "UPDATE table_name SET status = 1 WHERE id = 10"
```

Generate rollback SQL for review without executing it:

```bash
scripts/db-query --env qa01 --generate-rollback "UPDATE table_name SET status = 1 WHERE id = 10" --key-columns id
```

Assemble a full repair package (pre-check, change, rollback, post-check) without executing:

```bash
scripts/db-query --env qa01 --repair "UPDATE table_name SET status = 1 WHERE id = 10" --key-columns id
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

## Audit Log

Every call that actually reaches a database — `--sql`, `--search-objects`, `--inspect`, `--preview-write`, `--generate-rollback`, and `--repair` — appends one JSON line to a local append-only audit log. Calls that never touch a database (`--setup-status`, `--check-sql`, `--list-envs`, `--print-command`) are not logged. The MCP adapter delegates to `scripts/db-query`, so its executions are audited through the same path.

Each entry records: `ts` (local ISO 8601), `event` (`sql`/`search_objects`/`inspect`/`preview_write`/`generate_rollback`/`repair`), `env` (connection name, or `null` for ad-hoc), `adhoc`, `mode` (`read`/`write`), `token`, `statement` (the executed SQL with the auto-appended limit, secrets redacted), `allow_write`, `exit_code`, `duration_ms`, `user`, and `pid`. Only the actual write path — a `sql` DML execution, or a `repair` run with `--allow-write` — records `mode: "write"`; `preview_write` and `generate_rollback` run read-only SELECTs and record `mode: "read"`.

Default location is `~/.local/state/database-cli/audit.log`. Resolution order:

1. `--audit-log <path>`
2. `DATABASE_CLI_AUDIT_LOG` environment variable
3. config `audit_log` (top-level or per-environment)
4. the default path above

Disable logging for a single call with `--no-audit`, or persistently with `"audit": false` in config (top-level or per-environment). Audit failures never block a query; a write error is reported to stderr and the query result is still returned. Inspect the trail with standard tools:

```bash
tail -n 20 ~/.local/state/database-cli/audit.log
```

Filter to write operations only:

```bash
grep '"mode": "write"' ~/.local/state/database-cli/audit.log
```

## Notes

- Direct config is preferred: the wrapper can build a temporary `sq` source from `driver`, `host`, `port`, `username`, and `password`. `database` and `schema` are optional defaults, not access limits.
- `sq sql` accepts a single SQL statement and supports JSON, CSV, Markdown, YAML, and text output.
- `sq inspect --json` can inspect source metadata, tables, and columns.
- Keep source handles and credentials in local config. Do not commit secrets to this skill.
