"""SQLAlchemy async engine and session factory for SQLite."""

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def create_engine_and_session(db_url: str = "sqlite+aiosqlite:///data/vespeiro.db"):
    """Create async engine + sessionmaker for the given database URL."""
    engine = create_async_engine(db_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, session_factory


# Default instances (can be overridden by calling create_engine_and_session again)
engine, async_session = create_engine_and_session()
