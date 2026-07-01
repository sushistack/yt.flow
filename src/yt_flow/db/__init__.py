from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

_engine = None


def init(db_url: str) -> None:
    global _engine
    # ponytail: StaticPool for in-memory SQLite (":memory:" or "sqlite://") — single shared connection
    if db_url in ("sqlite://", "sqlite:///:memory:"):
        _engine = create_engine(
            db_url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
        _engine = create_engine(db_url, connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(_engine)


def get_session():
    with Session(_engine) as session:
        yield session
