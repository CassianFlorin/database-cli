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

For non-interactive setup:

```bash
scripts/init-config \
  --env qa01 \
  --driver mysql \
  --host mysql-qa01.example.internal \
  --username readonly_user \
  --password-env QA01_DB_PASSWORD
```

If the user already has DBHub configured, import existing sources from its TOML:

```bash
scripts/init-config --from-dbhub-toml /path/to/dbhub.toml --force
```

This reads DBHub `sources[].id` as environment names and `sources[].dsn` as connection definitions. The generated file is still local, ignored, and `0600`. Do not print the TOML, DSN, or generated config because DBHub DSNs may contain passwords.

The resulting `connections.local.json` uses direct database connection fields:

```json
{
  "environments": {
    "qa01": {
      "driver": "mysql",
      "host": "mysql-qa01.example.internal",
      "username": "readonly_user",
      "password": "replace-with-local-password",
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

- `driver`: Required for direct config. Supported direct drivers: `mysql`, `postgres`, `sqlite3`, `duckdb`, `sqlserver`, `clickhouse`.
- `host`: Required for network databases.
- `port`: Optional. If omitted, the DSN uses only the host/domain. This supports domains whose proxy already maps the database port.
- `database`: Optional for network databases. Use it only when the server requires a default catalog/database at login. Otherwise qualify tables in SQL, such as `SELECT col FROM dbname.schema.table` or `SELECT col FROM dbname.table`.
- `username`: Optional if the database allows anonymous access.
- `password`: Optional. Store only in ignored local files.
- `password_env`: Optional. Name of an environment variable containing the password; preferred for production credentials.
- `params`: Optional object of URL query parameters. The query wrapper filters parameters by driver before creating the temporary `sq` source; for example, DBHub MySQL `sslmode=disable` is not passed to MySQL because the driver rejects it.
- `source`: Optional advanced mode. Use an existing `sq` source handle such as `@qnvip_qa01_commerce`; if present, direct connection fields are ignored.
- `schema`: Optional. Passed as `--src.schema`; avoid setting it when the user should choose the database/schema in each SQL statement.
- `sq_config`: Optional at top level or per environment. Passed to `sq --config`.
- `limit_style`: Optional. Use `limit` for MySQL/Postgres/SQLite/DuckDB. Use `none` if the database does not accept appended `LIMIT`.

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

The direct config is intentionally not database-scoped by default. The configured environment represents a database server/instance and authorization context. The user decides which database/schema/table to query by writing fully-qualified SQL.

When a password is configured, the wrapper does not place the password in the command-line DSN. It invokes `sq add --password` and passes the password on stdin.

## Safety Model

The wrapper blocks common mutation and side-effect SQL before calling `sq`. This is a guardrail, not a full SQL parser. If a query is questionable, rewrite it as a simpler read-only `SELECT` with exact predicates.
