"""Create the disposable local verification database without touching demo data."""

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

SOURCE_URL = "postgresql+asyncpg://nyan_local:nyan_local_only@127.0.0.1:5432/nyan_shop_bot"


async def main() -> None:
    engine = create_async_engine(SOURCE_URL, hide_parameters=True, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            exists = await connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = 'nyan_shop_bot_test'")
            )
            if exists is None:
                await connection.execute(text("CREATE DATABASE nyan_shop_bot_test"))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
