from __future__ import annotations

import uuid
from collections.abc import Sequence

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_session
from ..identity.api import Actor, actor_by_id, current_actor, require_role
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


class ProblemUpdate(BaseModel):
    equation: str | None = None
    variable: str | None = Field(default=None, min_length=1, max_length=1)
    difficulty: int | None = Field(default=None, ge=1, le=3)
    skills: list[str] | None = None
    active: bool | None = None


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


class MembershipRead(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID

    model_config = {"from_attributes": True}


class AssignmentCreate(BaseModel):
    problem_id: uuid.UUID
    title: str = Field(min_length=1, max_length=120)


class AssignmentRead(BaseModel):
    id: uuid.UUID
    problem_id: uuid.UUID
    title: str

    model_config = {"from_attributes": True}


def _problem_read(problem: Problem) -> ProblemRead:
    return ProblemRead.model_validate(problem)


def _attempt_problem(attempt: Attempt) -> ProblemRead:
    return ProblemRead.model_validate(attempt.problem_snapshot)


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
            select(Attempt.problem_snapshot, Submission.correct)
            .join(Submission, Submission.attempt_id == Attempt.id)
            .where(Attempt.user_id == user_id)
            .order_by(Submission.created_at)
        )
    ).all()
    return [
        Observation(skill, correct)
        for snapshot, correct in rows
        for skill in _attempt_problem_from_snapshot(snapshot).skills
    ]


def _attempt_problem_from_snapshot(snapshot: dict) -> ProblemRead:
    return ProblemRead.model_validate(snapshot)


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


async def _owned_problem(
    session: AsyncSession, problem_id: uuid.UUID, teacher_id: uuid.UUID
) -> Problem:
    problem = await session.scalar(
        select(Problem).where(Problem.id == problem_id, Problem.owner_id == teacher_id)
    )
    if not problem:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Problem not found")
    return problem


@router.patch("/problems/{problem_id}", response_model=ProblemRead)
async def update_problem(
    problem_id: uuid.UUID,
    payload: ProblemUpdate,
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(require_role("teacher")),
) -> Problem:
    problem = await _owned_problem(session, problem_id, actor.id)
    changes = payload.model_dump(exclude_unset=True)
    equation = changes.get("equation", problem.equation)
    variable = changes.get("variable", problem.variable)
    try:
        default_service().validate(equation, variable)
    except EquationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    for field, value in changes.items():
        setattr(problem, field, value)
    problem.version += 1
    await session.commit()
    await session.refresh(problem)
    return problem


@router.delete(
    "/problems/{problem_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
async def deactivate_problem(
    problem_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(require_role("teacher")),
) -> None:
    problem = await _owned_problem(session, problem_id, actor.id)
    problem.active = False
    problem.version += 1
    await session.commit()


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
        return AttemptRead(
            id=existing.id,
            problem_id=existing.problem_id,
            problem=_attempt_problem(existing),
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
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        concurrent = await session.scalar(
            select(Attempt).where(
                Attempt.user_id == actor.id, Attempt.idempotency_key == idempotency_key
            )
        )
        if concurrent:
            return AttemptRead(
                id=concurrent.id,
                problem_id=concurrent.problem_id,
                problem=_attempt_problem(concurrent),
            )
        raise
    await session.refresh(attempt)
    return AttemptRead(id=attempt.id, problem_id=problem.id, problem=_problem_read(problem))


@router.post("/attempts/{attempt_id}/hints", response_model=HintRead)
async def request_hint(
    attempt_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(current_actor),
) -> HintRecord:
    attempt = await _owned_attempt(session, attempt_id, actor)
    problem = _attempt_problem(attempt)
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
    problem = _attempt_problem(attempt)
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
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        concurrent = await session.scalar(
            select(Submission).where(
                Submission.attempt_id == attempt.id,
                Submission.idempotency_key == idempotency_key,
            )
        )
        if concurrent:
            return concurrent
        raise
    await session.refresh(submission)
    return submission


@router.post("/attempts/{attempt_id}/explanation", response_model=ExplanationRead)
async def explain_attempt(
    attempt_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(current_actor),
) -> ExplanationRecord:
    attempt = await _owned_attempt(session, attempt_id, actor)
    problem = _attempt_problem(attempt)
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
            select(Attempt.problem_snapshot, Submission.correct, Submission.points)
            .join(Submission, Submission.attempt_id == Attempt.id)
            .where(Attempt.user_id == actor.id)
        )
    ).all()
    correct_rows = [row for row in rows if row.correct]
    labels = {1: "Fácil", 2: "Médio", 3: "Difícil"}
    by_difficulty = {label: 0 for label in labels.values()}
    for row in correct_rows:
        problem = _attempt_problem_from_snapshot(row.problem_snapshot)
        by_difficulty[labels[problem.difficulty]] += 1
    observations = [
        Observation(skill, row.correct)
        for row in rows
        for skill in _attempt_problem_from_snapshot(row.problem_snapshot).skills
    ]
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
    return (
        await session.scalars(
            select(Classroom).where(Classroom.teacher_id == actor.id, Classroom.active)
        )
    ).all()


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


@router.patch("/classrooms/{classroom_id}", response_model=ClassroomRead)
async def update_classroom(
    classroom_id: uuid.UUID,
    payload: ClassroomCreate,
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(require_role("teacher")),
) -> Classroom:
    classroom = await _owned_classroom(session, classroom_id, actor.id)
    classroom.name = payload.name
    await session.commit()
    await session.refresh(classroom)
    return classroom


@router.delete(
    "/classrooms/{classroom_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
async def delete_classroom(
    classroom_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(require_role("teacher")),
) -> None:
    classroom = await _owned_classroom(session, classroom_id, actor.id)
    classroom.active = False
    await session.commit()


@router.get("/classrooms/{classroom_id}/memberships", response_model=list[MembershipRead])
async def list_memberships(
    classroom_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(require_role("teacher")),
) -> Sequence[Membership]:
    await _owned_classroom(session, classroom_id, actor.id)
    return (
        await session.scalars(select(Membership).where(Membership.classroom_id == classroom_id))
    ).all()


@router.post(
    "/classrooms/{classroom_id}/memberships",
    response_model=MembershipRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_membership(
    classroom_id: uuid.UUID,
    payload: MembershipCreate,
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(require_role("teacher")),
) -> Membership:
    await _owned_classroom(session, classroom_id, actor.id)
    student = await actor_by_id(session, payload.student_id)
    if student is None or student.role != "student":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Student not found")
    membership = Membership(classroom_id=classroom_id, student_id=payload.student_id)
    session.add(membership)
    await session.commit()
    await session.refresh(membership)
    return membership


@router.delete(
    "/classrooms/{classroom_id}/memberships/{membership_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
async def delete_membership(
    classroom_id: uuid.UUID,
    membership_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(require_role("teacher")),
) -> None:
    await _owned_classroom(session, classroom_id, actor.id)
    membership = await session.scalar(
        select(Membership).where(
            Membership.id == membership_id, Membership.classroom_id == classroom_id
        )
    )
    if not membership:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Membership not found")
    await session.delete(membership)
    await session.commit()


@router.get("/classrooms/{classroom_id}/assignments", response_model=list[AssignmentRead])
async def list_assignments(
    classroom_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(require_role("teacher")),
) -> Sequence[Assignment]:
    await _owned_classroom(session, classroom_id, actor.id)
    return (
        await session.scalars(select(Assignment).where(Assignment.classroom_id == classroom_id))
    ).all()


@router.post(
    "/classrooms/{classroom_id}/assignments",
    response_model=AssignmentRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_assignment(
    classroom_id: uuid.UUID,
    payload: AssignmentCreate,
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(require_role("teacher")),
) -> Assignment:
    await _owned_classroom(session, classroom_id, actor.id)
    if not await session.get(Problem, payload.problem_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Problem not found")
    assignment = Assignment(classroom_id=classroom_id, **payload.model_dump())
    session.add(assignment)
    await session.commit()
    await session.refresh(assignment)
    return assignment


@router.delete(
    "/classrooms/{classroom_id}/assignments/{assignment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
async def delete_assignment(
    classroom_id: uuid.UUID,
    assignment_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(require_role("teacher")),
) -> None:
    await _owned_classroom(session, classroom_id, actor.id)
    assignment = await session.scalar(
        select(Assignment).where(
            Assignment.id == assignment_id, Assignment.classroom_id == classroom_id
        )
    )
    if not assignment:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")
    await session.delete(assignment)
    await session.commit()


@router.get("/classrooms/{classroom_id}/report")
async def classroom_report(
    classroom_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    actor: Actor = Depends(require_role("teacher")),
) -> dict:
    await _owned_classroom(session, classroom_id, actor.id)
    rows = (
        await session.execute(
            select(
                Attempt.user_id,
                func.count(Submission.id),
                func.sum(Submission.points),
            )
            .join(Submission, Submission.attempt_id == Attempt.id)
            .join(Membership, Membership.student_id == Attempt.user_id)
            .where(Membership.classroom_id == classroom_id)
            .group_by(Attempt.user_id)
        )
    ).all()
    return {
        "classroom_id": classroom_id,
        "students": [
            {"student_id": user_id, "submissions": submissions, "points": points or 0}
            for user_id, submissions, points in rows
        ],
    }
