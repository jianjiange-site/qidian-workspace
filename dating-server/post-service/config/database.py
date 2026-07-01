"""SQLAlchemy async engine and session configuration for post-service.

All values flow through ``config.settings`` (env vars > Nacos > defaults),
so sensitive credentials never touch the repo.
"""
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from typing import Optional
from sqlalchemy.orm import DeclarativeBase
from . import settings

# --------------- connection ---------------

_engine: Optional["AsyncEngine"] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


async def init_db() -> None:
    """Call after ``await settings.init_config()`` to build the engine.

    Must run before any module imports ``get_db`` or ``Base``.
    """
    global _engine, _session_factory

    DATABASE_URL = settings.get(
        "postgres.url",
        default="postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/dating_dev",
    )

    _engine = create_async_engine(
        DATABASE_URL,
        echo=settings.get("sql.echo") in ("1", "true", "True"),
        pool_size=settings.get_int("db.pool_size", default=10),
        max_overflow=settings.get_int("db.max_overflow", default=20),
        pool_pre_ping=True,
    )

    _session_factory = async_sessionmaker(
        _engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
# --------------- declarative base ---------------

class Base(DeclarativeBase):
    pass


# --------------- session dependency ---------------

async def get_db() -> AsyncSession:
    """Yield a database session for use in service / manager layers."""
    if _session_factory is None:
        raise RuntimeError("Database not initialized — call init_db() first")
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
