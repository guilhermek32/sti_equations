from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

import httpx

from .engine import EquationEngine, MathstepsFallback
from .engine import EquationError as EquationError


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


@dataclass(frozen=True)
class Explanation:
    text: str
    provider: str
    model: str
    prompt_version: str
    fallback: bool = False


class StepProvider(Protocol):
    def steps(self, equation: str, variable: str) -> list[Hint]: ...


class ExplanationProvider(Protocol):
    async def explain(self, equation: str, hints: list[Hint]) -> Explanation: ...


class LlamaCppExplanationProvider:
    PROMPT_VERSION = "explanation-pt-v1"

    def __init__(self, base_url: str, model: str, timeout: float = 45.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout

    async def explain(self, equation: str, hints: list[Hint]) -> Explanation:
        prompt = (
            "Explique em português, de forma breve e pedagógica, como resolver a equação "
            f"{equation}. Use estas dicas matematicamente verificadas: "
            + " ".join(hint.text for hint in hints)
            + " Não altere a equação e não invente resultados."
        )
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/v1/chat/completions",
                json={
                    "model": self._model,
                    "temperature": 0.1,
                    "max_tokens": 384,
                    "reasoning_effort": "low",
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            response.raise_for_status()
            payload = response.json()
        try:
            text = payload["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError, AttributeError) as exc:
            raise RuntimeError("Explanation provider returned malformed output") from exc
        if not text:
            raise RuntimeError("Explanation provider returned an empty explanation")
        return Explanation(
            text=text,
            provider="llama.cpp",
            model=self._model,
            prompt_version=self.PROMPT_VERSION,
        )


def deterministic_explanation(hints: list[Hint]) -> Explanation:
    text = " ".join(hint.text for hint in hints) or "Não há dicas disponíveis para esta equação."
    return Explanation(
        text=text,
        provider="deterministic",
        model="sympy-v1",
        prompt_version="native-hints-v1",
        fallback=True,
    )


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
