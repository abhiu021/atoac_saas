"""SQLAlchemy engine/session. DATABASE_URL swaps SQLite <-> Postgres with no code change."""
from sqlalchemy import create_engine, event, inspect as sa_inspect
from sqlalchemy.orm import declarative_base, sessionmaker

from config import settings

_is_sqlite = settings.DATABASE_URL.startswith("sqlite")
# check_same_thread off + a busy timeout so concurrent negotiation threads can share
# the SQLite file; WAL (set below) lets readers and a writer proceed in parallel.
connect_args = {"check_same_thread": False, "timeout": 30} if _is_sqlite else {}
engine = create_engine(settings.DATABASE_URL, connect_args=connect_args)

if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency: yields a session, always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    import models  # noqa: F401 — ensures tables are registered before create_all

    Base.metadata.create_all(bind=engine)
    _ensure_columns()


# Lightweight additive migration: add new columns to existing tables (SQLite AND
# Postgres) so a model change doesn't require dropping the DB — create_all() only
# creates missing *tables*, never new columns. (A full solution would use Alembic.)
# Boolean defaults differ by dialect (SQLite: 1, Postgres: true), so DDL is per-dialect.
_ADDED_COLUMNS = {
    "products": [
        ("strategy", {"sqlite": "VARCHAR DEFAULT 'balanced'", "postgresql": "VARCHAR DEFAULT 'balanced'"}),
        ("auto_negotiate", {"sqlite": "BOOLEAN DEFAULT 1", "postgresql": "BOOLEAN DEFAULT true"}),
        ("image_url", {"sqlite": "TEXT", "postgresql": "TEXT"}),
    ],
    "agreements": [
        ("basket_id", {"sqlite": "INTEGER", "postgresql": "INTEGER"}),
    ],
}


def _ensure_columns():
    dialect = engine.dialect.name  # 'sqlite' | 'postgresql'
    try:
        insp = sa_inspect(engine)
        tables = set(insp.get_table_names())
    except Exception:
        return
    with engine.begin() as conn:
        for table, cols in _ADDED_COLUMNS.items():
            if table not in tables:
                continue  # fresh DB — create_all already built the full schema
            existing = {c["name"] for c in insp.get_columns(table)}
            for col, ddl_by_dialect in cols:
                ddl = ddl_by_dialect.get(dialect)
                if col in existing or not ddl:
                    continue
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
