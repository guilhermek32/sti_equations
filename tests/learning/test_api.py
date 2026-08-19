from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from sti_equations.app import app
from sti_equations.database import Base, get_session, make_engine
from sti_equations.identity.api import Actor, current_actor
from sti_equations.learning.models import Problem


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession]:
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as database_session:
        yield database_session
    await engine.dispose()


@pytest.fixture
async def client(session: AsyncSession) -> AsyncGenerator[AsyncClient]:
    actor = Actor(id=uuid.uuid4(), email="student@example.com", role="student")

    async def session_override():
        yield session

    async def actor_override():
        return actor

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[current_actor] = actor_override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()


@pytest.fixture
async def problem(session: AsyncSession) -> Problem:
    item = Problem(
        equation="2*x + 1 = 2",
        variable="x",
        difficulty=2,
        skills=["fractions"],
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


async def test_score_is_server_side_idempotent_and_supports_fractions(
    client: AsyncClient, problem: Problem
) -> None:
    attempt_response = await client.post(
        "/v1/attempts",
        json={"problem_id": str(problem.id), "score": 9999},
        headers={"Idempotency-Key": "attempt-one"},
    )
    assert attempt_response.status_code == 201, attempt_response.text
    repeated = await client.post(
        "/v1/attempts",
        json={"problem_id": str(problem.id)},
        headers={"Idempotency-Key": "attempt-one"},
    )
    assert repeated.json()["id"] == attempt_response.json()["id"]

    attempt_id = attempt_response.json()["id"]
    submission = await client.post(
        f"/v1/attempts/{attempt_id}/submissions",
        json={"answer": "1/2", "correct": True, "points": 9999},
        headers={"Idempotency-Key": "submission-one"},
    )
    assert submission.status_code == 200, submission.text
    assert submission.json() == {
        "id": submission.json()["id"],
        "correct": True,
        "points": 10,
    }
    repeated_submission = await client.post(
        f"/v1/attempts/{attempt_id}/submissions",
        json={"answer": "100"},
        headers={"Idempotency-Key": "submission-one"},
    )
    assert repeated_submission.json() == submission.json()


async def test_hint_penalty_never_makes_score_negative(
    client: AsyncClient, problem: Problem
) -> None:
    attempt = await client.post(
        "/v1/attempts",
        json={"problem_id": str(problem.id)},
        headers={"Idempotency-Key": "hinted"},
    )
    attempt_id = attempt.json()["id"]
    hint = await client.post(f"/v1/attempts/{attempt_id}/hints")
    assert hint.status_code == 200
    exhausted = None
    for _ in range(10):
        exhausted = await client.post(f"/v1/attempts/{attempt_id}/hints")
        if exhausted.status_code == 409:
            break
    assert exhausted and exhausted.status_code == 409
    submission = await client.post(
        f"/v1/attempts/{attempt_id}/submissions",
        json={"answer": "1/2"},
        headers={"Idempotency-Key": "hinted-submission"},
    )
    assert submission.json()["points"] >= 0


async def test_progress_is_derived_and_uses_consistent_labels(
    client: AsyncClient, problem: Problem
) -> None:
    attempt = await client.post(
        "/v1/attempts",
        json={"problem_id": str(problem.id)},
        headers={"Idempotency-Key": "progress"},
    )
    await client.post(
        f"/v1/attempts/{attempt.json()['id']}/submissions",
        json={"answer": "1/2"},
        headers={"Idempotency-Key": "progress-submission"},
    )
    response = await client.get("/v1/me/progress", headers={"X-Request-ID": "test-id"})
    assert response.headers["X-Request-ID"] == "test-id"
    assert response.json()["by_difficulty"] == {"Fácil": 0, "Médio": 1, "Difícil": 0}
    assert response.json()["points"] == 10


async def test_attempt_ownership_is_enforced(client: AsyncClient) -> None:
    response = await client.post(
        f"/v1/attempts/{uuid.uuid4()}/submissions",
        json={"answer": "1"},
        headers={"Idempotency-Key": "foreign"},
    )
    assert response.status_code == 404
    assert set(response.json()) == {"code", "message", "request_id"}
    assert response.json()["request_id"]
