"""SQLAlchemy async engine and session configuration for post-service.

All values flow through ``config.settings`` (env vars > Nacos > defaults),
so sensitive credentials never touch the repo.
"""
import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from . import settings

logger = logging.getLogger(__name__)

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

    # --------------- auto-create tables ---------------

    import model  # noqa: F401  — register all ORM tables on Base.metadata

    async with _engine.begin() as conn:
        try:
            await conn.run_sync(Base.metadata.create_all)
            logger.info("All tables created / verified successfully.")
        except Exception:
            logger.warning(
                "Failed to create tables — the database might not exist yet "
                "or the user lacks DDL privileges. The service will continue "
                "without schema auto-creation.",
                exc_info=True,
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


class _SessionContext:
    """显式事务上下文，供 service 层手动控制 commit/rollback。"""

    def __init__(self):
        self.session: AsyncSession | None = None

    async def __aenter__(self) -> AsyncSession:
        if _session_factory is None:
            raise RuntimeError("Database not initialized — call init_db() first")
        self.session = _session_factory()
        return self.session

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session is None:
            return
        try:
            if exc_type is None:
                await self.session.commit()
            else:
                await self.session.rollback()
        finally:
            await self.session.close()


def get_session() -> _SessionContext:
    """返回一个显式事务上下文管理器。"""
    return _SessionContext()