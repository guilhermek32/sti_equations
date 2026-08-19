from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, default=uuid.uuid4)


class Problem(Base):
    __tablename__ = "problem"
    __table_args__ = {"schema": "learning"}
    id: Mapped[uuid.UUID] = uuid_pk()
    equation: Mapped[str] = mapped_column(Text)
    variable: Mapped[str] = mapped_column(String(1))
    difficulty: Mapped[int] = mapped_column(Integer)
    skills: Mapped[list[str]] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("identity.user.id"))


class Attempt(Base):
    __tablename__ = "attempt"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key"),
        {"schema": "learning"},
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("identity.user.id"), index=True)
    problem_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("learning.problem.id"))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    problem_snapshot: Mapped[dict] = mapped_column(JSON)
    scoring_version: Mapped[str] = mapped_column(String(32), default="score-v1")
    solver_version: Mapped[str] = mapped_column(String(32), default="sympy-v1")
    model_version: Mapped[str] = mapped_column(String(32), default="bkt-v1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class HintRecord(Base):
    __tablename__ = "hint"
    __table_args__ = {"schema": "learning"}
    id: Mapped[uuid.UUID] = uuid_pk()
    attempt_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("learning.attempt.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    skill: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class Submission(Base):
    __tablename__ = "submission"
    __table_args__ = (
        UniqueConstraint("attempt_id", "idempotency_key"),
        {"schema": "learning"},
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    attempt_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("learning.attempt.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    answer: Mapped[str] = mapped_column(Text)
    correct: Mapped[bool] = mapped_column(Boolean)
    points: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class ExplanationRecord(Base):
    __tablename__ = "explanation"
    __table_args__ = {"schema": "learning"}
    id: Mapped[uuid.UUID] = uuid_pk()
    attempt_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("learning.attempt.id"), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(120))
    prompt_version: Mapped[str] = mapped_column(String(32))
    text: Mapped[str] = mapped_column(Text)
    fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class Classroom(Base):
    __tablename__ = "classroom"
    __table_args__ = {"schema": "learning"}
    id: Mapped[uuid.UUID] = uuid_pk()
    teacher_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("identity.user.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Membership(Base):
    __tablename__ = "membership"
    __table_args__ = (
        UniqueConstraint("classroom_id", "student_id"),
        {"schema": "learning"},
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    classroom_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("learning.classroom.id"))
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("identity.user.id"))


class Assignment(Base):
    __tablename__ = "assignment"
    __table_args__ = {"schema": "learning"}
    id: Mapped[uuid.UUID] = uuid_pk()
    classroom_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("learning.classroom.id"))
    problem_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("learning.problem.id"))
    title: Mapped[str] = mapped_column(String(120))
