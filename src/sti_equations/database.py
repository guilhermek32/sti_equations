from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


def make_engine(url: str | None = None) -> AsyncEngine:
    database_url = url or get_settings().database_url
    options = {}
    if database_url.startswith("sqlite"):
        options["execution_options"] = {
            "schema_translate_map": {"identity": None, "learning": None}
        }
    return create_async_engine(database_url, **options)


engine = make_engine()
async_session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession]:
    async with async_session_factory() as session:
        yield session


async def create_database(database_engine: AsyncEngine = engine) -> None:
    # Import owners only to register their tables in the common metadata.
    from .identity import api as identity_api  # noqa: F401
    from .learning import api as learning_api  # noqa: F401

    async with database_engine.begin() as connection:
        if database_engine.dialect.name == "postgresql":
            await connection.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS identity")
            await connection.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS learning")
        await connection.run_sync(Base.metadata.create_all)
