"""Migration helpers for SQLAlchemy schema drift."""
from typing import List, Dict, Any, Optional
from sqlalchemy import inspect, text, MetaData, Table, Column, create_engine
from sqlalchemy.schema import CreateTable
from app.core.db import engine, DATABASE_URL
from app.core.config import settings, build_database_url, resolve_db_mode

class MigrationService:

    @classmethod
    def is_blank(cls, base) -> bool:
        try:
            inspector = inspect(engine)
            existing = set(inspector.get_table_names())
            model_tables = set(base.metadata.tables.keys())
            return not existing.intersection(model_tables)
        except Exception:
            return True

    @classmethod
    def auto_init_blank(cls, base):
        if cls.is_blank(base):
            base.metadata.create_all(bind=engine)
            return True
        return False

    @classmethod
    def diff_schema(cls, base) -> List[Dict[str, Any]]:
        """Return a list of operations required to bring existing DB up to model state.
        Each op: {type, table, column, sql, risk, message}
        """
        inspector = inspect(engine)
        ops: List[Dict[str, Any]] = []
        existing_tables = inspector.get_table_names()
        model_tables = {t: base.metadata.tables[t] for t in base.metadata.tables.keys()}

        # New tables
        for name, table in model_tables.items():
            if name not in existing_tables:
                create_sql = str(CreateTable(table).compile(engine)).strip()
                ops.append({
                    "type": "create_table",
                    "table": name,
                    "column": None,
                    "sql": create_sql + ";",
                    "risk": "low",
                    "message": f"Create new table `{name}`. No data loss."
                })

        # Missing columns / type changes in existing tables
        for name, table in model_tables.items():
            if name not in existing_tables:
                continue
            existing_cols = {c['name']: c for c in inspector.get_columns(name)}
            for col in table.columns:
                if col.name not in existing_cols:
                    col_sql = str(CreateColumn(col).compile(engine)).strip()
                    ops.append({
                        "type": "add_column",
                        "table": name,
                        "column": col.name,
                        "sql": f"ALTER TABLE {name} ADD COLUMN {col_sql};",
                        "risk": "low",
                        "message": f"Add column `{col.name}` to `{name}`. Existing rows get NULL/default."
                    })

        # Columns present in DB but missing in model -> potential data loss
        for name in existing_tables:
            if name not in model_tables:
                continue
            model_cols = {c.name for c in model_tables[name].columns}
            for col in inspector.get_columns(name):
                if col['name'] not in model_cols:
                    ops.append({
                        "type": "drop_column",
                        "table": name,
                        "column": col['name'],
                        "sql": f"ALTER TABLE {name} DROP COLUMN {col['name']};",
                        "risk": "high",
                        "message": f"Drop column `{col['name']}` from `{name}`. DATA LOSS: all values in this column will be removed."
                    })

        # Tables present in DB but missing in model -> potential full table loss
        for name in existing_tables:
            if name not in model_tables:
                ops.append({
                    "type": "drop_table",
                    "table": name,
                    "column": None,
                    "sql": f"DROP TABLE {name};",
                    "risk": "high",
                    "message": f"Drop table `{name}`. DATA LOSS: entire table and all its rows will be removed."
                })

        return ops

    @classmethod
    def run_ops(cls, ops: List[Dict[str, Any]]) -> Dict[str, Any]:
        with engine.begin() as conn:
            for op in ops:
                conn.execute(text(op['sql']))
        return {"applied": len(ops)}

    @classmethod
    def run_ops_on(cls, ops: List[Dict[str, Any]], target_engine) -> Dict[str, Any]:
        """Run migration ops against a specific engine (used by switch-db)."""
        with target_engine.begin() as conn:
            for op in ops:
                conn.execute(text(op['sql']))
        return {"applied": len(ops)}

    @classmethod
    def diff_schema_on(cls, base, target_engine) -> List[Dict[str, Any]]:
        """Diff schema against a specific engine instead of the global one."""
        inspector = inspect(target_engine)
        ops: List[Dict[str, Any]] = []
        existing_tables = inspector.get_table_names()
        model_tables = {t: base.metadata.tables[t] for t in base.metadata.tables.keys()}

        for name, table in model_tables.items():
            if name not in existing_tables:
                create_sql = str(CreateTable(table).compile(target_engine)).strip()
                ops.append({
                    "type": "create_table",
                    "table": name,
                    "column": None,
                    "sql": create_sql + ";",
                    "risk": "low",
                    "message": f"Create new table `{name}`. No data loss."
                })

        for name, table in model_tables.items():
            if name not in existing_tables:
                continue
            existing_cols = {c['name']: c for c in inspector.get_columns(name)}
            for col in table.columns:
                if col.name not in existing_cols:
                    col_sql = str(CreateColumn(col).compile(target_engine)).strip()
                    ops.append({
                        "type": "add_column",
                        "table": name,
                        "column": col.name,
                        "sql": f"ALTER TABLE {name} ADD COLUMN {col_sql};",
                        "risk": "low",
                        "message": f"Add column `{col.name}` to `{name}`. Existing rows get NULL/default."
                    })

        for name in existing_tables:
            if name not in model_tables:
                continue
            model_cols = {c.name for c in model_tables[name].columns}
            for col in inspector.get_columns(name):
                if col['name'] not in model_cols:
                    ops.append({
                        "type": "drop_column",
                        "table": name,
                        "column": col['name'],
                        "sql": f"ALTER TABLE {name} DROP COLUMN {col['name']};",
                        "risk": "high",
                        "message": f"Drop column `{col['name']}` from `{name}`. DATA LOSS: all values in this column will be removed."
                    })

        for name in existing_tables:
            if name not in model_tables:
                ops.append({
                    "type": "drop_table",
                    "table": name,
                    "column": None,
                    "sql": f"DROP TABLE {name};",
                    "risk": "high",
                    "message": f"Drop table `{name}`. DATA LOSS: entire table and all its rows will be removed."
                })

        return ops


# Helper for CreateColumn DDL rendering
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.schema import CreateColumn

@compiles(CreateColumn)
def _compile_create_column(element, compiler, **kw):
    col = element.element
    # Include server_default and nullable
    text = compiler.get_column_specification(col, **kw)
    if col.server_default:
        text += " DEFAULT " + col.server_default.arg.text
    return text
