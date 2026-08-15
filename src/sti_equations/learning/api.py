from __future__ import annotations

import uuid
from collections.abc import Sequence

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_session
from ..identity.api import Actor, current_actor, require_role
from ..modeling.api import Candidate, Observation, hint_depth, mastery_by_skill, select_next
from ..tutoring.api import (
    EquationError,
    LlamaCppExplanationProvider,
    default_service,
    deterministic_explanation,
)
from .models import (
    Assignment,
    Attempt,
    Classroom,
    ExplanationRecord,
    HintRecord,
    Membership,
    Problem,
    Submission,
)
from .seed import PROBLEMS

router = APIRouter(prefix="/v1", tags=["learning"])


def problem_catalog() -> list[tuple[str, str, int, list[str]]]:
    return [
        (equation, variable, difficulty, list(skills))
        for equation, variable, difficulty, skills in PROBLEMS
    ]


async def seed_problems(session: AsyncSession) -> None:
    if not await session.scalar(select(func.count()).select_from(Problem)):
        session.add_all(
            [
                Problem(
                    equation=equation,
                    variable=variable,
                    difficulty=difficulty,
                    skills=skills,
                )
                for equation, variable, difficulty, skills in PROBLEMS
            ]
        )
        await session.commit()


class ProblemRead(BaseModel):
    id: uuid.UUID
    equation: str
    variable: str
    difficulty: int
    skills: list[str]
    version: int

    model_config = {"from_attributes": True}


class ProblemCreate(BaseModel):
    equation: str
    variable: str = Field(min_length=1, max_length=1)
    difficulty: int = Field(ge=1, le=3)
    skills: list[str] = Field(min_length=1)


class AttemptCreate(BaseModel):
    problem_id: uuid.UUID


class AttemptRead(BaseModel):
    id: uuid.UUID
    problem_id: uuid.UUID
    problem: ProblemRead


class HintRead(BaseModel):
    position: int
    text: str
    skill: str

    model_config = {"from_attributes": True}


class SubmissionCreate(BaseModel):
    answer: str = Field(min_length=1, max_length=200)


class SubmissionRead(BaseModel):
    id: uuid.UUID
    correct: bool
    points: int

    model_config = {"from_attributes": True}


class ProgressRead(BaseModel):
    solved: int
    points: int
    by_difficulty: dict[str, int]
    mastery: dict[str, float]


class ExplanationRead(BaseModel):
    text: str
    provider: str
    model: str
    prompt_version: str
    fallback: bool

    model_config = {"from_attributes": True}


class ClassroomCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class ClassroomRead(BaseModel):
    id: uuid.UUID
    name: str

    model_config = {"from_attributes": True}


class MembershipCreate(BaseModel):
    student_id: uuid.UUID


class AssignmentCreate(BaseModel):
    problem_id: uuid.UUID
    title: str = Field(min_length=1, max_length=120)


def _problem_read(problem: Problem) -> ProblemRead:
    return ProblemRead.model_validate(problem)


async def _owned_attempt(session: AsyncSession, attempt_id: uuid.UUID, actor: Actor) -> Attempt:
    attempt = await session.scalar(
        select(Attempt).where(Attempt.id == attempt_id, Attempt.user_id == actor.id)
    )
    if not attempt:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attempt not found")
    return attempt


async def _history(session: AsyncSession, user_id: uuid.UUID) -> list[Observation]:
    rows = (
        await session.execute(
            select(Problem.skills, Submission.correct)
            .join(Attempt, Attempt.problem_id == Problem.id)
            .join(Submission, Submission.attempt_id == Attempt.id)
            .where(Attempt.user_id == user_id)
            .order_by(Submission.created_at)
        )
    ).all()
    return [Observation(skill, correct) for skills, correct in rows for skill in skills]


@router.get("/problems", response_model=list[ProblemRead])
async def list_problems(
    session: AsyncSession = Depends(get_session), actor: Actor = Depends(current_actor)
) -> Sequence[Problem]:
    del actor
    return (await session.scalars(select(Problem).where(Problem.active))).all()


@router.get("/problems/next", response_model=ProblemRead)
async def next_problem(
    session: AsyncSession = Depends(get_session), actor: Actor = Depends(current_actor)
) -> Problem:
    problems = (await session.scalars(select(Problem).where(Problem.active))).all()
    mastery = mastery_by_skill(await _history(session, actor.id))
    selected = select_next(
        [Candidate(str(p.id), tuple(p.skills), p.difficulty) for p in problems], mastery
    )
    if selected is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No active problems")
    return next(problem for problem in problems if str(problem.id) == selected.problem_id)


@router.post("/problems", response_model=ProblemRead, status_code=status.HTTP_201_CREATED)
async def create_problem(
    payload: ProblemCreate,
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(require_role("teacher")),
) -> Problem:
    try:
        default_service().validate(payload.equation, payload.variable)
    except EquationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    problem = Problem(**payload.model_dump(), owner_id=actor.id)
    session.add(problem)
    await session.commit()
    await session.refresh(problem)
    return problem


@router.post("/attempts", response_model=AttemptRead, status_code=status.HTTP_201_CREATED)
async def start_attempt(
    payload: AttemptCreate,
    idempotency_key: str = Header(min_length=1, max_length=128, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(current_actor),
) -> AttemptRead:
    existing = await session.scalar(
        select(Attempt).where(
            Attempt.user_id == actor.id, Attempt.idempotency_key == idempotency_key
        )
    )
    if existing:
        problem = await session.get(Problem, existing.problem_id)
        return AttemptRead(
            id=existing.id, problem_id=existing.problem_id, problem=_problem_read(problem)
        )
    problem = await session.scalar(
        select(Problem).where(Problem.id == payload.problem_id, Problem.active)
    )
    if not problem:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Problem not found")
    snapshot = _problem_read(problem).model_dump(mode="json")
    attempt = Attempt(
        user_id=actor.id,
        problem_id=problem.id,
        idempotency_key=idempotency_key,
        problem_snapshot=snapshot,
    )
    session.add(attempt)
    await session.commit()
    await session.refresh(attempt)
    return AttemptRead(id=attempt.id, problem_id=problem.id, problem=_problem_read(problem))


@router.post("/attempts/{attempt_id}/hints", response_model=HintRead)
async def request_hint(
    attempt_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(current_actor),
) -> HintRecord:
    attempt = await _owned_attempt(session, attempt_id, actor)
    problem = await session.get(Problem, attempt.problem_id)
    hints = default_service().hints(problem.equation, problem.variable)
    used = await session.scalar(
        select(func.count()).select_from(HintRecord).where(HintRecord.attempt_id == attempt.id)
    )
    if used >= len(hints):
        raise HTTPException(status.HTTP_409_CONFLICT, "No more hints are available")
    mastery = mastery_by_skill(await _history(session, actor.id))
    skill = problem.skills[min(used, len(problem.skills) - 1)]
    depth = hint_depth(mastery.get(skill, 0.2), len(hints))
    position = min(used + depth - 1, len(hints) - 1)
    hint = HintRecord(
        attempt_id=attempt.id,
        position=used,
        text=hints[position].text,
        skill=hints[position].skill,
    )
    session.add(hint)
    await session.commit()
    await session.refresh(hint)
    return hint


@router.post("/attempts/{attempt_id}/submissions", response_model=SubmissionRead)
async def submit_answer(
    attempt_id: uuid.UUID,
    payload: SubmissionCreate,
    idempotency_key: str = Header(min_length=1, max_length=128, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(current_actor),
) -> Submission:
    attempt = await _owned_attempt(session, attempt_id, actor)
    existing = await session.scalar(
        select(Submission).where(
            Submission.attempt_id == attempt.id,
            Submission.idempotency_key == idempotency_key,
        )
    )
    if existing:
        return existing
    problem = await session.get(Problem, attempt.problem_id)
    try:
        correct = default_service().is_equivalent_answer(
            problem.equation, problem.variable, payload.answer
        )
    except EquationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    used_hints = await session.scalar(
        select(func.count()).select_from(HintRecord).where(HintRecord.attempt_id == attempt.id)
    )
    points = max(0, 5 * problem.difficulty - used_hints) if correct else 0
    submission = Submission(
        attempt_id=attempt.id,
        idempotency_key=idempotency_key,
        answer=payload.answer,
        correct=correct,
        points=points,
    )
    session.add(submission)
    await session.commit()
    await session.refresh(submission)
    return submission


@router.post("/attempts/{attempt_id}/explanation", response_model=ExplanationRead)
async def explain_attempt(
    attempt_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(current_actor),
) -> ExplanationRecord:
    attempt = await _owned_attempt(session, attempt_id, actor)
    problem = await session.get(Problem, attempt.problem_id)
    service = default_service()
    service.validate(problem.equation, problem.variable)
    hints = service.hints(problem.equation, problem.variable)
    settings = get_settings()
    explanation = deterministic_explanation(hints)
    if settings.explanation_url:
        try:
            explanation = await LlamaCppExplanationProvider(
                settings.explanation_url, settings.explanation_model
            ).explain(problem.equation, hints)
        except (httpx.HTTPError, RuntimeError):
            pass
    record = ExplanationRecord(attempt_id=attempt.id, **explanation.__dict__)
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record


@router.get("/me/progress", response_model=ProgressRead)
async def progress(
    session: AsyncSession = Depends(get_session), actor: Actor = Depends(current_actor)
) -> ProgressRead:
    rows = (
        await session.execute(
            select(Problem.difficulty, Problem.skills, Submission.correct, Submission.points)
            .join(Attempt, Attempt.problem_id == Problem.id)
            .join(Submission, Submission.attempt_id == Attempt.id)
            .where(Attempt.user_id == actor.id)
        )
    ).all()
    correct_rows = [row for row in rows if row.correct]
    labels = {1: "Fácil", 2: "Médio", 3: "Difícil"}
    by_difficulty = {label: 0 for label in labels.values()}
    for row in correct_rows:
        by_difficulty[labels[row.difficulty]] += 1
    observations = [Observation(skill, row.correct) for row in rows for skill in row.skills]
    return ProgressRead(
        solved=len(correct_rows),
        points=sum(row.points for row in rows),
        by_difficulty=by_difficulty,
        mastery=mastery_by_skill(observations),
    )


async def _owned_classroom(
    session: AsyncSession, classroom_id: uuid.UUID, teacher_id: uuid.UUID
) -> Classroom:
    classroom = await session.scalar(
        select(Classroom).where(Classroom.id == classroom_id, Classroom.teacher_id == teacher_id)
    )
    if not classroom:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Classroom not found")
    return classroom


@router.get("/classrooms", response_model=list[ClassroomRead])
async def list_classrooms(
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(require_role("teacher")),
) -> Sequence[Classroom]:
    return (await session.scalars(select(Classroom).where(Classroom.teacher_id == actor.id))).all()


@router.post("/classrooms", response_model=ClassroomRead, status_code=status.HTTP_201_CREATED)
async def create_classroom(
    payload: ClassroomCreate,
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(require_role("teacher")),
) -> Classroom:
    classroom = Classroom(teacher_id=actor.id, name=payload.name)
    session.add(classroom)
    await session.commit()
    await session.refresh(classroom)
    return classroom


@router.post("/classrooms/{classroom_id}/memberships", status_code=status.HTTP_201_CREATED)
async def add_membership(
    classroom_id: uuid.UUID,
    payload: MembershipCreate,
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(require_role("teacher")),
) -> dict[str, uuid.UUID]:
    await _owned_classroom(session, classroom_id, actor.id)
    membership = Membership(classroom_id=classroom_id, student_id=payload.student_id)
    session.add(membership)
    await session.commit()
    return {"id": membership.id}


@router.post("/classrooms/{classroom_id}/assignments", status_code=status.HTTP_201_CREATED)
async def create_assignment(
    classroom_id: uuid.UUID,
    payload: AssignmentCreate,
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(require_role("teacher")),
) -> dict[str, uuid.UUID]:
    await _owned_classroom(session, classroom_id, actor.id)
    if not await session.get(Problem, payload.problem_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Problem not found")
    assignment = Assignment(classroom_id=classroom_id, **payload.model_dump())
    session.add(assignment)
    await session.commit()
    return {"id": assignment.id}
