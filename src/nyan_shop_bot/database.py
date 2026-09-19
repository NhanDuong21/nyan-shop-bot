"""Minimal PostgreSQL connectivity used by readiness and migrations."""

from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


class DatabaseProbe(Protocol):
    """Small boundary that keeps readiness testable without a real database."""

    async def ping(self) -> bool: ...

    async def close(self) -> None: ...


class PostgresDatabase:
    """Async PostgreSQL probe; business persistence arrives in later issues."""

    def __init__(self, database_url: str) -> None:
        self._engine: AsyncEngine = create_async_engine(
            database_url,
            pool_pre_ping=True,
            hide_parameters=True,
        )

    async def ping(self) -> bool:
        async with self._engine.connect() as connection:
            value: int | None = await connection.scalar(text("SELECT 1"))
        return value == 1

    async def close(self) -> None:
        await self._engine.dispose()
