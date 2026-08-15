from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from sti_equations.app import app
from sti_equations.database import Base, get_session, make_engine
from sti_equations.identity.models import AccessToken


@pytest.fixture
async def auth_context() -> AsyncGenerator[tuple[AsyncClient, AsyncSession]]:
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:

        async def session_override():
            yield session

        app.dependency_overrides[get_session] = session_override
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, session
        app.dependency_overrides.clear()
    await engine.dispose()


async def test_registration_login_and_logout_revoke_database_session(auth_context) -> None:
    client, session = auth_context
    registered = await client.post(
        "/v1/auth/register",
        json={"email": "student@example.com", "password": "password123", "role": "teacher"},
    )
    assert registered.status_code == 201, registered.text
    assert registered.json()["role"] == "student"
    logged_in = await client.post(
        "/v1/auth/login",
        data={"username": "student@example.com", "password": "password123"},
    )
    assert logged_in.status_code == 204, logged_in.text
    assert await session.scalar(select(func.count()).select_from(AccessToken)) == 1
    assert (await client.get("/v1/problems")).status_code == 200
    logged_out = await client.post("/v1/auth/logout")
    assert logged_out.status_code == 204
    assert await session.scalar(select(func.count()).select_from(AccessToken)) == 0
    assert (await client.get("/v1/problems")).status_code == 401


async def test_short_password_uses_standard_error_envelope(auth_context) -> None:
    client, _ = auth_context
    response = await client.post(
        "/v1/auth/register", json={"email": "student@example.com", "password": "short"}
    )
    assert response.status_code == 400
    assert set(response.json()) == {"code", "message", "request_id"}


async def test_expired_database_session_is_rejected(auth_context) -> None:
    client, session = auth_context
    await client.post(
        "/v1/auth/register",
        json={"email": "expired@example.com", "password": "password123"},
    )
    await client.post(
        "/v1/auth/login",
        data={"username": "expired@example.com", "password": "password123"},
    )
    token = await session.scalar(select(AccessToken))
    token.created_at = datetime.now(UTC) - timedelta(hours=2)
    await session.commit()
    assert (await client.get("/v1/problems")).status_code == 401
