# Database CLI Configuration

Keep real database connection details outside committed skill files.

The wrapper reads config from the first existing path:

1. `--config <path>`
2. `$DATABASE_CLI_CONFIG`
3. `./connections.local.json`
4. `~/.config/database-cli/connections.json`

## Recommended Config

After installing or copying the plugin, run the setup entrypoint from the plugin root:

```bash
scripts/install
```

It checks for `sq`, optionally installs it with Homebrew, then asks the user for the SQL connection address and authorization details.

If you only need to create or update config, run the initializer directly:

```bash
scripts/init-config
```

The initializer writes `skills/database-cli/connections.local.json` with file mode `0600` when run through the plugin root wrapper. If run from inside `skills/database-cli`, it writes that same local config file.

The initializer can accept either split fields or a user-provided database URL. Explicit flags override values parsed from the URL:

```bash
scripts/init-config \
  --env qa01 \
  --url "mysql://mysql-qa01.example.internal:3306/qnvip_center_order?charset=utf8mb4" \
  --username readonly_user \
  --password-env QA01_DB_PASSWORD
```

For non-interactive setup:

```bash
scripts/init-config \
  --env qa01 \
  --url "mysql://mysql-qa01.example.internal" \
  --display-name "QNVIP QA01" \
  --environment qa01 \
  --project qnvip \
  --description "Shared QA readonly connection; search all visible schemas unless narrowed." \
  --alias qa-01 \
  --username readonly_user \
  --password-env QA01_DB_PASSWORD
```

The resulting `connections.local.json` uses direct database connection fields:

```json
{
  "environments": {
    "qa01": {
      "display_name": "QNVIP QA01",
      "environment": "qa01",
      "project": "qnvip",
      "description": "Shared QA readonly connection; search all visible schemas unless narrowed.",
      "aliases": ["qa-01", "test"],
      "driver": "mysql",
      "host": "mysql-qa01.example.internal",
      "username": "readonly_user",
      "password": "replace-with-local-password",
      "max_rows": 200,
      "limit_style": "limit"
    },
    "prod": {
      "driver": "mysql",
      "host": "mysql-prod.example.internal",
      "username": "readonly_user",
      "password_env": "QNVIP_PROD_DB_PASSWORD",
      "limit_style": "limit"
    }
  }
}
```

Fields:

- `display_name`: Optional human-readable connection name shown by `--list-envs`.
- `environment`: Optional environment label, such as `qa01`, `prod`, or `staging`.
- `project`: Optional project or business domain, such as `qnvip`.
- `description`: Optional guidance for humans and Agents about when to use this connection.
- `aliases`: Optional list of extra names that resolve to this environment. For example, `qa-01` can resolve to `qa01`.
- `driver`: Required for direct config. Supported direct drivers: `mysql`, `postgres`, `sqlite3`, `duckdb`, `sqlserver`, `clickhouse`.
- `url`: Initializer input only. Parses driver, host, port, database/path, username, password, and URL query params into the stored fields below. Prefer passing username/password separately when possible.
- `host`: Required for network databases.
- `port`: Optional. If omitted, the DSN uses only the host/domain. This supports domains whose proxy already maps the database port.
- `database`: Optional for network databases. Use it only when the server requires a default catalog/database at login. Otherwise qualify tables in SQL, such as `SELECT col FROM dbname.schema.table` or `SELECT col FROM dbname.table`.
- `username`: Optional if the database allows anonymous access.
- `password`: Optional. Store only in ignored local files.
- `password_env`: Optional. Name of an environment variable containing the password; preferred for production credentials.
- `params`: Optional object of URL query parameters. The query wrapper filters parameters by driver before creating the temporary `sq` source.
- `source`: Optional advanced mode. Use an existing `sq` source handle such as `@qnvip_qa01_commerce`; if present, direct connection fields are ignored.
- `schema`: Optional. Passed as `--src.schema`; avoid setting it when the user should choose the database/schema in each SQL statement.
- `sq_config`: Optional at top level or per environment. Passed to `sq --config`.
- `limit_style`: Optional. Use `limit` for MySQL/Postgres/SQLite/DuckDB. Use `none` if the database does not accept appended `LIMIT`.
- `max_rows`: Optional positive integer at top level or per environment. It is a hard cap for auto-appended limits and larger existing `LIMIT` clauses.
- `readonly`: Optional boolean. Only `true` or omitted is supported. `false` is rejected because this skill never executes write SQL.

## Optional MCP Custom Tools

The MCP adapter also exposes `add_connection` for running Agents that need to add or update a connection without restart. It writes the same `connections.local.json` format via the initializer path, then later MCP tool calls read the updated file.

Example `add_connection` arguments:

```json
{
  "config": "/path/to/connections.local.json",
  "env": "qa02",
  "url": "mysql://mysql-qa02.example.internal:3306/qnvip_center_order",
  "username": "readonly_user",
  "password_env": "QA02_DB_PASSWORD",
  "display_name": "QNVIP QA02",
  "aliases": ["qa-02"],
  "max_rows": 100
}
```

Top-level `tools` entries expose optional parameterized read-only tools from `scripts/database-mcp`. This is an adapter convenience for MCP clients, not the core product model. The rendered SQL still goes through `scripts/db-query`, so CLI safety checks and `max_rows` remain authoritative.

```json
{
  "environments": {
    "qa01": {
      "driver": "mysql",
      "host": "mysql-qa01.example.internal",
      "username": "readonly_user",
      "password_env": "QA01_DB_PASSWORD",
      "max_rows": 100
    }
  },
  "tools": {
    "find_order": {
      "description": "Find one order by order number.",
      "env": "qa01",
      "sql": "SELECT id, order_no, status FROM cc_order WHERE order_no = :order_no",
      "parameters": {
        "order_no": {
          "type": "string",
          "description": "Order number."
        }
      }
    }
  }
}
```

Rules:

- Tool names and parameter names must use letters, numbers, or underscores and start with a letter or underscore.
- `sql` must be a read-only statement after parameters are rendered.
- Placeholders use `:param_name`; values are rendered as SQL literals and escaped.
- Parameter schemas support `type`, `description`, `enum`, `default`, `optional`, `minimum`, and `maximum`.
- Reserved call-time keys are `config`, `_format`, `_limit`, and `_print_command`.
- Do not define repair or mutation SQL as a custom tool.

## Advanced Handle Config

If you already manage sources with `sq add`, the config can point to the existing handle:

```json
{
  "sq_config": "/Users/me/.config/sq/sq.yml",
  "environments": {
    "qa01": {
      "source": "@qnvip_qa01_commerce",
      "schema": "qnvip_center_commerce"
    }
  }
}
```

## Direct Config Behavior

When an environment uses direct fields, `scripts/db-query` builds a DSN, creates a temporary `sq` source, runs the read-only query or inspect command, then deletes the temporary config. It does not require the user to run `sq add` manually.

The direct config is intentionally not database-scoped by default. The configured environment represents a database server/instance and authorization context. Do not create one connection per database unless those databases require different hosts or credentials.

For metadata discovery, omit `--schema` first so `scripts/db-query --search-objects` searches the schemas visible to the configured account. Add `--schema` only after the user narrows the target or the result set is too broad.

For data lookup, use fully-qualified table names after discovery, such as `SELECT col FROM dbname.table_name WHERE ...`.

When a password is configured, the wrapper does not place the password in the command-line DSN. It invokes `sq add --password` and passes the password on stdin.

## Safety Model

The wrapper blocks common mutation and side-effect SQL before calling `sq`. This is a guardrail, not a full SQL parser. If a query is questionable, rewrite it as a simpler read-only `SELECT` with exact predicates.

When `max_rows` is configured, it is a hard safety cap. A larger CLI `--limit` or a larger SQL `LIMIT` is reduced to `max_rows`.
