"""SQLAlchemy engine/session. DATABASE_URL swaps SQLite <-> Postgres with no code change."""
from sqlalchemy import create_engine, event
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


# Lightweight additive migration: add new columns to existing SQLite tables so a
# model change doesn't require dropping the DB. (A full solution would use Alembic.)
_ADDED_COLUMNS = {
    "products": {"strategy": "VARCHAR DEFAULT 'balanced'"},
    "agreements": {"basket_id": "INTEGER"},
}


def _ensure_columns():
    if not _is_sqlite:
        return
    with engine.begin() as conn:
        for table, cols in _ADDED_COLUMNS.items():
            try:
                existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            except Exception:
                continue
            for col, ddl in cols.items():
                if col not in existing:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
