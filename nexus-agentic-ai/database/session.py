from collections.abc import AsyncGenerator

from app.config import settings
from app.logging import logger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """SQLAlchemy Declarative Base Model."""

    pass


def get_engine():
    """Create async database engine with sqlite fallback for tests/local scaffold."""
    db_url = settings.database_url
    # If postgresql asyncpg is not reachable in local standalone dev, allow sqlite+aiosqlite
    if "sqlite" in db_url:
        return create_async_engine(db_url, echo=settings.debug)
    return create_async_engine(db_url, echo=settings.debug, pool_pre_ping=True)


engine = get_engine()
async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for injecting async DB sessions."""
    async with async_session_factory() as session:
        try:
            yield session
        except Exception as exc:
            await session.rollback()
            logger.error(f"Database session rollback triggered: {exc}")
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Create database tables if they do not exist."""
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database schema initialized successfully.")
    except Exception as exc:
        logger.warning(
            "Could not connect to external DB (expected in standalone local dev): %s",
            exc,
        )
