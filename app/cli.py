#!/usr/bin/env python3
"""DockLiner management CLI.

Commands:
    setup                  Run first-time setup (env + port + deps).
    delete-local-db        Delete the SQLite file(s) after confirming a live DB is configured.
    switch-db MODE [TYPE]  Switch DB_MODE to test or live and re-run migrations.
    migrate                Run pending migrations against the current database.

Examples:
    python -m app.cli setup
    python -m app.cli switch-db live postgres
    python -m app.cli migrate
    python -m app.cli delete-local-db
"""
import os
import sys
import socket
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


def _is_prime(n: int) -> bool:
    if n < 2:
        return False
    if n % 2 == 0:
        return n == 2
    r = int(n ** 0.5)
    for i in range(3, r + 1, 2):
        if n % i == 0:
            return False
    return True


def _port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def _next_free_port(start: int = 50000) -> int:
    port = max(start, 50000)
    while True:
        if _is_prime(port):
            port += 1
            continue
        if _port_free("0.0.0.0", port):
            return port
        port += 1


def _write_env_default(port: int, db_mode: str = "auto") -> None:
    env_path = ROOT / ".env"
    if env_path.exists():
        backup = ROOT / ".env.bak"
        backup.write_text(env_path.read_text(), encoding="utf-8")
        print(f"[cli] Backed up existing .env to {backup}")

    env_text = f"""# DockLiner configuration
DOCKLINER_SECRET_KEY=change-me
DOCKLINER_HOST=0.0.0.0
DOCKLINER_PORT={port}

# Database mode: auto | test | live
DOCKLINER_DB_MODE={db_mode}

# Database type: sqlite | mysql | postgres
DOCKLINER_DB_TYPE=sqlite

# SQLite paths
DOCKLINER_SQLITE_DB_PATH=./dockliner.db
DOCKLINER_SQLITE_TEST_DB_PATH=./dockliner_test.db
"""
    env_path.write_text(env_text, encoding="utf-8")
    print(f"[cli] Wrote .env with DOCKLINER_PORT={port}, DOCKLINER_DB_MODE={db_mode}")


def cmd_setup(args: argparse.Namespace) -> int:
    from app.core.config import settings, resolve_port, is_port_free

    port = None
    if args.port:
        port = int(args.port)
        if not is_port_free(settings.HOST, port):
            print(f"[cli] ERROR: Requested port {port} is already in use on {settings.HOST}.", file=sys.stderr)
            return 1
    elif "DOCKLINER_PORT" in os.environ:
        port = settings.PORT
        if not is_port_free(settings.HOST, port):
            print(f"[cli] ERROR: Configured DOCKLINER_PORT={port} is already in use.", file=sys.stderr)
            return 1
    else:
        port = _next_free_port()
        print(f"[cli] No port configured. Auto-selected free port: {port}")

    _write_env_default(port, db_mode=args.db_mode)
    return 0


def cmd_delete_local_db(args: argparse.Namespace) -> int:
    # Import config AFTER env is loaded (it validates on import).
    from app.core.config import settings, resolve_db_mode, resolve_db_type
    from app.core.db import DATABASE_URL

    mode = resolve_db_mode()
    db_type = resolve_db_type(mode)

    if db_type == "sqlite" and mode != "live":
        print("[cli] ERROR: Refusing to delete local SQLite while DB_TYPE=sqlite; this would destroy your active database.", file=sys.stderr)
        return 1

    candidates = []
    for attr in ("SQLITE_DB_PATH", "SQLITE_TEST_DB_PATH", "DB_PATH"):
        val = getattr(settings, attr, None)
        if val:
            candidates.append(Path(val).expanduser().resolve())

    deleted = []
    skipped = []
    errors = []
    for p in dict.fromkeys(candidates):
        if p.exists():
            try:
                p.unlink()
                deleted.append(str(p))
            except Exception as e:
                errors.append(f"{p}: {e}")
        else:
            skipped.append(str(p))

    print(f"[cli] Current database: {DATABASE_URL}")
    print(f"[cli] Deleted SQLite files: {deleted or 'none'}")
    print(f"[cli] Missing SQLite files: {skipped or 'none'}")
    if errors:
        print(f"[cli] Errors: {errors}")
    return 0 if not errors else 1


def cmd_switch_db(args: argparse.Namespace) -> int:
    mode = (args.mode or "").lower().strip()
    db_type = (args.type or "sqlite").lower().strip()
    if mode not in ("test", "live"):
        print("[cli] ERROR: switch-db requires mode 'test' or 'live'.", file=sys.stderr)
        return 1
    if db_type not in ("sqlite", "mysql", "postgres", "postgresql"):
        print("[cli] ERROR: type must be sqlite, mysql, or postgres.", file=sys.stderr)
        return 1

    env_path = ROOT / ".env"
    env_lines = []
    if env_path.exists():
        env_lines = env_path.read_text(encoding="utf-8").splitlines()

    def upsert(lines: list, key: str, value: str) -> list:
        found = False
        out = []
        for line in lines:
            if line.strip().startswith(f"{key}=") or line.strip().startswith(f"# {key}="):
                out.append(f"{key}={value}")
                found = True
            else:
                out.append(line)
        if not found:
            out.append(f"{key}={value}")
        return out

    env_lines = upsert(env_lines, "DOCKLINER_DB_MODE", mode)
    env_lines = upsert(env_lines, "DOCKLINER_DB_TYPE", db_type)
    env_path.write_text("\n".join(env_lines) + "\n", encoding="utf-8")

    # Reload process env and validate before running migrations
    os.environ["DOCKLINER_DB_MODE"] = mode
    os.environ["DOCKLINER_DB_TYPE"] = db_type

    # Re-importing config validates live vars for live mode
    import importlib
    import app.core.config as config_mod
    importlib.reload(config_mod)
    from app.core.config import settings, build_database_url, require_live_vars
    from app.core.db import Base

    new_url = build_database_url()
    print(f"[cli] Switched to DB_MODE={mode}, DB_TYPE={db_type}")
    print(f"[cli] New database URL: {new_url}")

    if mode == "live":
        require_live_vars()
        print("[cli] Live database variables validated.")

    # Create a fresh engine/session for the new URL and run migrations
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine_kwargs = {"connect_args": {"check_same_thread": False}} if new_url.startswith("sqlite") else {}
    new_engine = create_engine(new_url, **engine_kwargs)

    from app.services.migration_service import MigrationService
    from app.models.project import Project, Deployment, AccessToken, HealthCheck, Metric, AuditLog, Webhook, Notification, GithubCache, SavedOrg, Download, ErrorLog  # noqa

    is_blank = MigrationService.is_blank(Base)
    if is_blank:
        Base.metadata.create_all(bind=new_engine)
        print("[cli] Created fresh schema (blank database).")
    else:
        ops = MigrationService.diff_schema_on(Base, new_engine)
        if ops:
            result = MigrationService.run_ops_on(ops, new_engine)
            print(f"[cli] Applied {result['applied']} migration operations.")
        else:
            print("[cli] No pending migrations.")
    return 0


def cmd_migrate(args: argparse.Namespace) -> int:
    from app.core.db import Base, engine
    from app.services.migration_service import MigrationService

    is_blank = MigrationService.is_blank(Base)
    if is_blank:
        Base.metadata.create_all(bind=engine)
        print("[cli] Created fresh schema (blank database).")
        return 0

    ops = MigrationService.diff_schema(Base)
    if not ops:
        print("[cli] No pending migrations.")
        return 0

    if args.dry_run:
        for op in ops:
            print(f"[cli] [{op['risk']}] {op['message']}")
            print(f"       SQL: {op['sql']}")
        return 0

    result = MigrationService.run_ops(ops)
    print(f"[cli] Applied {result['applied']} migration operations.")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="dockliner", description="DockLiner management CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_setup = sub.add_parser("setup", help="First-time setup: choose a free port and write .env")
    p_setup.add_argument("--port", type=int, help="Explicit port (optional)")
    p_setup.add_argument("--db-mode", default="auto", help="Default DB_MODE (auto/test/live)")

    sub.add_parser("delete-local-db", help="Delete local SQLite files after switching to live DB")

    p_switch = sub.add_parser("switch-db", help="Switch DB_MODE and run migrations")
    p_switch.add_argument("mode", choices=["test", "live"], help="Target DB mode")
    p_switch.add_argument("type", nargs="?", default="sqlite", help="Database type (sqlite/mysql/postgres)")

    p_migrate = sub.add_parser("migrate", help="Run pending migrations on current database")
    p_migrate.add_argument("--dry-run", action="store_true", help="Show pending operations without applying")

    args = parser.parse_args(argv)

    handlers = {
        "setup": cmd_setup,
        "delete-local-db": cmd_delete_local_db,
        "switch-db": cmd_switch_db,
        "migrate": cmd_migrate,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
