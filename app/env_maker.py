"""
DockLiner .env maker / refiner.

Given the current .env content (or none), produce a clean, fully-commented,
organized .env file. It preserves user overrides, fills in missing accepted
variables with defaults, and keeps unknown/custom variables in an Extras section.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import List, Tuple, Optional, Dict

_ENV_PREFIX = "DOCKLINER_"


@dataclass
class EnvVar:
    key: str
    value: str
    comment: bool = False


# ---------------------------------------------------------------------------
# Accepted variables grouped by section.
# Each entry: (key, default_value, inline_description)
# Each entry: (key, default_value, inline_description, active_by_default)
SECTIONS: List[Tuple[str, str, Optional[str], bool]] = [
    (
        "Core server settings",
        "Required for the application to start. HOST accepts a comma-separated list of interfaces. "
        "PORT defaults to 50021 (the first prime in the 50xxx range). "
        "If PORT is occupied and PORT_SELECTION=auto, ALLOWED_PORTS is tried in order.",
        [
            ("SECRET_KEY", "change-me", "Root session secret — auto-generated if left as change-me", True),
            ("HOST", "0.0.0.0", "Comma-separated interfaces, e.g. 0.0.0.0,127.0.0.1,::1", True),
            ("PORT", "50021", "Port to listen on (default 50021)", True),
            (
                "PORT_SELECTION",
                "strict",
                "strict = fail if occupied | auto = pick next prime from ALLOWED_PORTS",
                True,
            ),
            (
                "ALLOWED_PORTS",
                "50021,50023,50033,50047,50051,50053,50069,50077,50087,50093,50101,50111,50119,50123",
                "Prime fallback ports when PORT_SELECTION=auto; ignored when PORT_SELECTION=strict",
                False,
            ),
            ("SERVICE", "dockliner", "systemd / Windows service name for Save & Restart", True),
        ],
    ),
    (
        "Database mode",
        "auto | test | live. auto resolves to live if any DB_LIVE_* var is set, otherwise test. "
        "SQLite is auto-migrated. Live mode with MySQL/Postgres is strict.",
        [
            ("DB_MODE", "auto", None, True),
        ],
    ),
    (
        "Database type",
        "sqlite | mysql | postgres. mysql is the canonical default. "
        "For SQLite, no further credentials are required.",
        [
            ("DB_TYPE", "sqlite", "sqlite is the zero-config default; mysql/postgres require credentials", True),
        ],
    ),
    (
        "Live database credentials",
        "Required when DB_MODE=live and DB_TYPE is not sqlite. "
        "DOCKLINER_USERS passwords must be BLAKE3 512-bit hex hashes (128 hex chars).",
        [
            ("DB_LIVE_HOST", "localhost", None, False),
            ("DB_LIVE_PORT", "3306", None, False),
            ("DB_LIVE_USER", "dockliner", None, False),
            ("DB_LIVE_PASSWORD", "", None, False),
            ("DB_LIVE_NAME", "dockliner", None, False),
        ],
    ),
    (
        "Test database credentials",
        "Required when DB_MODE=test and DB_TYPE is not sqlite. "
        "These are used for the test/isolated database.",
        [
            ("DB_TEST_HOST", "localhost", None, False),
            ("DB_TEST_PORT", "3306", None, False),
            ("DB_TEST_USER", "dockliner", None, False),
            ("DB_TEST_PASSWORD", "", None, False),
            ("DB_TEST_NAME", "dockliner_test", None, False),
        ],
    ),
    (
        "SQLite paths",
        "Used when DB_TYPE=sqlite. Files are created relative to the project root if missing.",
        [
            ("SQLITE_DB_PATH", "./dockliner.db", "Live/production SQLite file", False),
            ("SQLITE_TEST_DB_PATH", "./dockliner_test.db", "Test SQLite file", False),
            ("SQLITE_DB_NAME", "dockliner", None, False),
        ],
    ),
    (
        "Users",
        "JSON array of {user, hash} objects. Passwords must be BLAKE3 512-bit hex hashes (128 hex chars). "
        "Example hash generation: echo -n 'your-password' | b3sum -l 64",
        [
            ("USERS", '[{"user":"root","hash":"9aa0a2b0f48247f8be3983b37fdbc13a4128da84d4a68ff6690d0202d8883c926f258640f9d8fad34f4b625043195da367307f04274618e734f7b5bf5641a663"}]', "Default root user with blake3('qwer.1234') 512-bit hash", True),
        ],
    ),
    (
        "Driver hints",
        "pymysql for MySQL, psycopg2 for PostgreSQL.",
        [
            ("DB_DRIVER", "pymysql", None, False),
        ],
    ),
    (
        "Runtime directories",
        "Where projects, downloads and logs are stored. Created automatically if missing.",
        [
            ("PROJECTS_DIR", "./projects", None, False),
            ("DOWNLOADS_DIR", "./downloads", None, False),
            ("LOGS_DIR", "./logs", None, False),
        ],
    ),
]

# Build a flat map of accepted keys to their default value.
ACCEPTED_DEFAULTS: Dict[str, str] = {}
for _title, _desc, items in SECTIONS:
    for key, default, _note, _active in items:
        ACCEPTED_DEFAULTS[key] = default


def _full_key(key: str) -> str:
    return f"{_ENV_PREFIX}{key}"


def _strip_key(full_key: str) -> str:
    if full_key.startswith(_ENV_PREFIX):
        return full_key[len(_ENV_PREFIX):]
    return full_key


def _is_our_var(full_key: str) -> bool:
    return full_key.startswith(_ENV_PREFIX) and _strip_key(full_key) in ACCEPTED_DEFAULTS


def _parse_env(content: str) -> Tuple[List[str], Dict[str, EnvVar]]:
    """
    Parse raw .env content.
    Returns (leading_comments_before_any_var, dict of full_key -> EnvVar).
    """
    vars_by_key: Dict[str, EnvVar] = {}
    leading_comments: List[str] = []
    seen_any_var = False

    for raw in content.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            if not seen_any_var:
                leading_comments.append(raw)
            continue
        if "=" not in stripped:
            continue
        key, _, value = raw.partition("=")
        key = key.strip()
        value = value.strip()
        if key:
            vars_by_key[key] = EnvVar(key=key, value=value, comment=False)
            seen_any_var = True

    return leading_comments, vars_by_key


def refine_env(content: str) -> str:
    """
    Rebuild .env content.

    Rules:
      - Keep every user-defined value (commented or uncommented) if the key is accepted.
      - Preserve non-default active values exactly (e.g. DB_TYPE=mysql2 stays as-is).
      - Fill missing accepted vars with defaults, commented or uncommented based on section.
      - Put unknown/custom vars in an 'Extras' section at the bottom.
    """
    _, user_vars = _parse_env(content)

    # Collect unknown/custom keys (anything starting with DOCKLINER_ that we don't manage)
    extras: List[EnvVar] = []
    for full_key, var in user_vars.items():
        if full_key.startswith(_ENV_PREFIX) and not _is_our_var(full_key):
            extras.append(var)

    lines: List[str] = [
        "# DockLiner environment configuration",
        "# Restart the application after editing for changes to take full effect.",
        "",
    ]

    for title, section_desc, items in SECTIONS:
        lines.append(f"# -----------------------------------------------------------------------------")
        lines.append(f"# {title}")
        if section_desc:
            lines.append(f"# {section_desc}")
        lines.append(f"# -----------------------------------------------------------------------------")

        for key, default, note, active_default in items:
            full_key = _full_key(key)
            user = user_vars.get(full_key)
            value: str
            active: bool
            if user and not user.comment:
                value = user.value
                active = True
            else:
                value = default
                active = active_default

            # Build comment lines for context
            if note:
                lines.append(f"# {note}")

            if active:
                # Preserve user's non-default value exactly
                lines.append(f"{full_key}={value}")
            else:
                lines.append(f"# {full_key}={value}")

        lines.append("")

    if extras:
        lines.append("# -----------------------------------------------------------------------------")
        lines.append("# Extras (custom / user-added variables)")
        lines.append("# -----------------------------------------------------------------------------")
        for var in extras:
            lines.append(f"{var.key}={var.value}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def validate_env_content(content: str) -> List[str]:
    """Parse .env content and return a list of validation errors."""
    errors: List[str] = []
    parsed: Dict[str, str] = {}

    for line_no, raw in enumerate(content.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            errors.append(f"Line {line_no}: expected KEY=VALUE format")
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        parsed[key] = value

    mode = parsed.get("DOCKLINER_DB_MODE", "auto").lower()
    if mode not in ("auto", "test", "live"):
        errors.append("DOCKLINER_DB_MODE must be one of: auto, test, live")

    db_type = parsed.get("DOCKLINER_DB_TYPE", "mysql").lower()
    if db_type not in ("sqlite", "mysql", "postgres", "postgresql"):
        errors.append("DOCKLINER_DB_TYPE must be one of: sqlite, mysql, postgres")

    port_sel = parsed.get("DOCKLINER_PORT_SELECTION", "strict").lower()
    if port_sel not in ("strict", "auto"):
        errors.append("DOCKLINER_PORT_SELECTION must be one of: strict, auto")

    if "DOCKLINER_PORT" in parsed:
        try:
            port = int(parsed["DOCKLINER_PORT"])
            if not (1 <= port <= 65535):
                errors.append("DOCKLINER_PORT must be between 1 and 65535")
        except ValueError:
            errors.append("DOCKLINER_PORT must be an integer")

    secret = parsed.get("DOCKLINER_SECRET_KEY", "")
    if secret and len(secret) < 8:
        errors.append("DOCKLINER_SECRET_KEY should be at least 8 characters")

    if mode == "live" and db_type != "sqlite":
        for var in ("DB_LIVE_HOST", "DB_LIVE_USER", "DB_LIVE_PASSWORD", "DB_LIVE_NAME"):
            key = f"DOCKLINER_{var}"
            if not parsed.get(key, "").strip():
                errors.append(f"DB_MODE=live with {db_type} requires {key}")

    if mode == "test" and db_type not in ("sqlite",):
        for var in ("DB_TEST_HOST", "DB_TEST_USER", "DB_TEST_PASSWORD", "DB_TEST_NAME"):
            key = f"DOCKLINER_{var}"
            if not parsed.get(key, "").strip():
                errors.append(f"DB_MODE=test with {db_type} requires {key}")

    return errors
