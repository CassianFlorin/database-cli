"""Helpers shared by the database-cli scripts.

These scripts are standalone executables rather than a package, so each one puts
its own directory on `sys.path` and imports this module by name. The install
path symlinks the whole skill directory, so this file travels with them.

What lives here is what must not drift between entry points. Config discovery
already had: `$DATABASE_CLI_CONFIG` was honoured by db-query and silently
ignored by the MCP adapter, so the two could read different files in one
session. The literal-quoting rules are the same hazard with worse consequences
-- a driver table that disagrees between the CLI and the adapter emits SQL that
is wrong on one of them.

Deliberately not shared: value-to-literal dispatch. db-query renders snapshot
rows for a rollback and the adapter renders validated tool parameters; the type
domains and the useful error wording genuinely differ. Both call `sql_literal`
below for the part that has to agree.
"""

import json
import os
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlparse


SKILL_ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILENAME = "connections.local.json"


class ConfigError(ValueError):
    """Configuration is missing, malformed, or asks for something disallowed.

    Subclasses ValueError so the MCP adapter's `except ValueError` handler
    reports it as a JSON-RPC error without needing to import this type.
    """


class UnsafeSqlError(ValueError):
    """SQL, or a value bound into it, cannot be handled safely."""


# --- config discovery -------------------------------------------------------


def config_paths(explicit_path=None):
    """Config file candidates, highest precedence first.

    Computed per call rather than at import: the MCP adapter is long-lived, and
    a module-level list would freeze `Path.cwd()` at start-up.
    """
    if explicit_path:
        return [Path(explicit_path).expanduser()]
    env_path = os.environ.get("DATABASE_CLI_CONFIG")
    if env_path:
        return [Path(env_path).expanduser()]
    return [
        SKILL_ROOT / CONFIG_FILENAME,
        Path.cwd() / CONFIG_FILENAME,
        Path.home() / ".config" / "database-cli" / "connections.json",
    ]


def load_config(explicit_path=None, required=True):
    """Return (config, path). Yields ({}, None) when absent and not required."""
    for path in config_paths(explicit_path):
        if path.exists():
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle), path
    if required:
        checked = ", ".join(str(path) for path in config_paths(explicit_path))
        raise ConfigError(f"No config file found. Checked: {checked}")
    return {}, None


# --- connection metadata ----------------------------------------------------


def parse_database_url(raw_url):
    """Split a user-supplied database URL into connection fields."""
    if not raw_url:
        return {}
    if "://" not in raw_url:
        return {"host": raw_url}

    parsed = urlparse(raw_url)
    values = {}
    if parsed.scheme:
        scheme = parsed.scheme.lower()
        values["driver"] = "sqlite3" if scheme == "sqlite" else scheme
    if parsed.hostname:
        values["host"] = parsed.hostname
    if parsed.port:
        values["port"] = parsed.port
    if parsed.username:
        values["username"] = unquote(parsed.username)
    if parsed.password:
        values["password"] = unquote(parsed.password)

    path = unquote(parsed.path.lstrip("/"))
    if path:
        if values.get("driver") in {"sqlite3", "duckdb"}:
            values["path"] = unquote(parsed.path)
        else:
            values["database"] = path

    params = {key: value for key, value in parse_qsl(parsed.query, keep_blank_values=True)}
    if params:
        values["params"] = params
    return values


def alias_values(env):
    """Extra names that resolve to this environment."""
    aliases = env.get("aliases", [])
    if isinstance(aliases, str):
        return [aliases]
    if isinstance(aliases, list):
        return [str(alias) for alias in aliases if str(alias)]
    return []


def env_driver(env):
    """Driver name for an environment, or "" when it declares none."""
    if not isinstance(env, dict):
        return ""
    for key in ("driver", "type"):
        if env.get(key):
            return str(env[key]).lower()
    return ""


# --- SQL literals -----------------------------------------------------------

# MySQL, MariaDB, and ClickHouse read a backslash inside a string literal as an
# escape, so `'ends with \'` swallows the closing quote. The rest follow the
# standard, where a backslash is an ordinary character and doubling it would
# corrupt the stored value. One rule cannot serve both, which is exactly why
# these tables must exist in one place.
BACKSLASH_ESCAPE_DRIVERS = {"mysql", "mariadb", "clickhouse"}
ANSI_LITERAL_DRIVERS = {"postgres", "postgresql", "sqlite", "sqlite3", "duckdb", "sqlserver"}


def sql_literal(value, driver):
    """Quote a string literal for `driver`.

    Doubling the quote is correct everywhere; the backslash is not, and the two
    dialects disagree in opposite directions. When the driver is unknown the
    value is still safe to emit as long as it holds no backslash -- that is the
    only character whose meaning differs, so it is the only one worth refusing.
    """
    text = str(value)
    driver = (driver or "").lower()
    if driver in BACKSLASH_ESCAPE_DRIVERS:
        text = text.replace("\\", "\\\\").replace("\0", "\\0")
    elif "\\" in text and driver not in ANSI_LITERAL_DRIVERS:
        raise UnsafeSqlError(
            "Cannot quote a value containing a backslash without knowing the driver: "
            "MySQL-family and standard SQL read it differently, so the literal would be "
            "wrong on one of them. Set 'driver' on this environment in the config."
        )
    return "'" + text.replace("'", "''") + "'"
