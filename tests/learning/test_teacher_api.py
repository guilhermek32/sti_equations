from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from sti_equations.app import app
from sti_equations.database import Base, get_session, make_engine
from sti_equations.identity.api import current_user
from sti_equations.identity.models import User
from sti_equations.learning.models import Attempt


@pytest.fixture
async def teacher_context() -> AsyncGenerator[tuple[AsyncClient, AsyncSession, dict, dict]]:
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        teacher_one = User(
            email="one@example.com", hashed_password="x", role="teacher", is_active=True
        )
        teacher_two = User(
            email="two@example.com", hashed_password="x", role="teacher", is_active=True
        )
        student = User(
            email="student@example.com", hashed_password="x", role="student", is_active=True
        )
        session.add_all([teacher_one, teacher_two, student])
        await session.commit()
        state = {"user": teacher_one}

        async def session_override():
            yield session

        async def user_override():
            return state["user"]

        app.dependency_overrides[get_session] = session_override
        app.dependency_overrides[current_user] = user_override
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield (
                client,
                session,
                state,
                {
                    "teacher_one": teacher_one,
                    "teacher_two": teacher_two,
                    "student": student,
                },
            )
        app.dependency_overrides.clear()
    await engine.dispose()


async def test_teacher_can_only_access_owned_classroom(teacher_context) -> None:
    client, _, state, users = teacher_context
    created = await client.post("/v1/classrooms", json={"name": "Class A"})
    assert created.status_code == 201, created.text
    classroom_id = created.json()["id"]
    state["user"] = users["teacher_two"]
    assert (await client.get("/v1/classrooms")).json() == []
    assert (
        await client.patch(f"/v1/classrooms/{classroom_id}", json={"name": "Stolen"})
    ).status_code == 404
    assert (await client.get(f"/v1/classrooms/{classroom_id}/report")).status_code == 404


async def test_problem_edits_preserve_attempt_snapshot_and_teacher_workflow(
    teacher_context,
) -> None:
    client, session, state, users = teacher_context
    problem_response = await client.post(
        "/v1/problems",
        json={
            "equation": "x + 1 = 2",
            "variable": "x",
            "difficulty": 1,
            "skills": ["isolate_variable"],
        },
    )
    assert problem_response.status_code == 201, problem_response.text
    problem_id = problem_response.json()["id"]
    classroom = await client.post("/v1/classrooms", json={"name": "Class A"})
    classroom_id = classroom.json()["id"]
    membership = await client.post(
        f"/v1/classrooms/{classroom_id}/memberships",
        json={"student_id": str(users["student"].id)},
    )
    assert membership.status_code == 201, membership.text
    assignment = await client.post(
        f"/v1/classrooms/{classroom_id}/assignments",
        json={"problem_id": problem_id, "title": "Week 1"},
    )
    assert assignment.status_code == 201, assignment.text

    state["user"] = users["student"]
    attempt = await client.post(
        "/v1/attempts",
        json={"problem_id": problem_id},
        headers={"Idempotency-Key": "snapshot"},
    )
    assert attempt.status_code == 201, attempt.text

    state["user"] = users["teacher_one"]
    updated = await client.patch(f"/v1/problems/{problem_id}", json={"equation": "x + 2 = 4"})
    assert updated.status_code == 200, updated.text
    assert updated.json()["version"] == 2
    stored_attempt = await session.scalar(select(Attempt))
    assert stored_attempt.problem_snapshot["equation"] == "x + 1 = 2"
    assert stored_attempt.problem_snapshot["version"] == 1

    state["user"] = users["student"]
    submission = await client.post(
        f"/v1/attempts/{attempt.json()['id']}/submissions",
        json={"answer": "1"},
        headers={"Idempotency-Key": "snapshot-submission"},
    )
    assert submission.status_code == 200, submission.text
    assert submission.json()["correct"] is True
    assert submission.json()["points"] == 5
    progress = await client.get("/v1/me/progress")
    assert progress.json()["by_difficulty"] == {"Fácil": 1, "Médio": 0, "Difícil": 0}
