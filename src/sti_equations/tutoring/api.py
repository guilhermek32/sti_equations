from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from .engine import EquationEngine, MathstepsFallback


class SolutionKind(StrEnum):
    UNIQUE = "unique"
    NONE = "none"
    INFINITE = "infinite"


@dataclass(frozen=True)
class Solution:
    kind: SolutionKind
    value: str | None = None


@dataclass(frozen=True)
class Hint:
    text: str
    skill: str


class StepProvider(Protocol):
    def steps(self, equation: str, variable: str) -> list[Hint]: ...


class TutoringService:
    def __init__(self, fallback: StepProvider | None = None) -> None:
        self._engine = EquationEngine(fallback)

    def solve(self, equation: str, variable: str) -> Solution:
        return self._engine.solve(equation, variable)

    def is_equivalent_answer(self, equation: str, variable: str, answer: str) -> bool:
        return self._engine.is_equivalent_answer(equation, variable, answer)

    def hints(self, equation: str, variable: str) -> list[Hint]:
        return self._engine.steps(equation, variable)

    def validate(self, equation: str, variable: str) -> None:
        self._engine.solve(equation, variable)


def default_service() -> TutoringService:
    script = Path(__file__).resolve().parents[3] / "ext/js/mathsteps/index.js"
    return TutoringService(MathstepsFallback(script))
