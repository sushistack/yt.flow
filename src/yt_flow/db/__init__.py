from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

_engine = None


def init(db_url: str) -> None:
    global _engine
    if _engine is not None:
        _engine.dispose()
    # ponytail: StaticPool for in-memory SQLite (":memory:" or "sqlite://") — single shared connection
    if db_url in ("sqlite://", "sqlite:///:memory:"):
        _engine = create_engine(
            db_url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
        # ponytail: WAL + busy_timeout — this file is shared with LangGraph's
        # AsyncSqliteSaver (pipeline/graph.py) on the same path; the default
        # rollback-journal mode's exclusive write lock collides under real
        # concurrent writes (surfaced by running the real app end-to-end, not
        # by pytest's decoupled test DBs).
        _engine = create_engine(db_url, connect_args={"check_same_thread": False, "timeout": 30})
        with _engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL")
    SQLModel.metadata.create_all(_engine)
    _ensure_card_columns(_engine)


def _ensure_card_columns(engine) -> None:
    """Additive ALTER TABLE for character_cards.status/style_epoch (Story 8.6).

    ``create_all`` only creates missing tables, not missing columns on an
    existing table — this repo has no other migration mechanism, so every
    ``init()`` call (not just the one-shot ``scripts/migrate_assets.py``)
    must self-heal a pre-8.6 DB or the first ``save_card``/``get_card`` call
    against it raises "no such column: status".
    """
    with engine.connect() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(character_cards)")}
        if "status" not in cols:
            conn.exec_driver_sql("ALTER TABLE character_cards ADD COLUMN status TEXT DEFAULT 'draft'")
        if "style_epoch" not in cols:
            conn.exec_driver_sql("ALTER TABLE character_cards ADD COLUMN style_epoch INTEGER DEFAULT 1")
        conn.commit()


def get_session():
    if _engine is None:
        raise RuntimeError("db.init() has not been called")
    with Session(_engine) as session:
        yield session


def get_engine():
    """Return the current SQLAlchemy engine (for background tasks)."""
    if _engine is None:
        raise RuntimeError("db.init() has not been called")
    return _engine
