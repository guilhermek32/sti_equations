from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

MODEL_VERSION = "bkt-v1"


@dataclass(frozen=True)
class BKTParameters:
    initial: float = 0.2
    learn: float = 0.15
    guess: float = 0.2
    slip: float = 0.1


@dataclass(frozen=True)
class Observation:
    skill: str
    correct: bool


@dataclass(frozen=True)
class Candidate:
    problem_id: str
    skills: tuple[str, ...]
    difficulty: int


DEFAULT_PARAMETERS = BKTParameters()


def update_mastery(
    prior: float, correct: bool, params: BKTParameters = DEFAULT_PARAMETERS
) -> float:
    if correct:
        evidence = prior * (1 - params.slip) + (1 - prior) * params.guess
        posterior = prior * (1 - params.slip) / evidence
    else:
        evidence = prior * params.slip + (1 - prior) * (1 - params.guess)
        posterior = prior * params.slip / evidence
    return posterior + (1 - posterior) * params.learn


def mastery_by_skill(
    observations: Iterable[Observation], params: BKTParameters = DEFAULT_PARAMETERS
) -> dict[str, float]:
    mastery: dict[str, float] = {}
    for observation in observations:
        prior = mastery.get(observation.skill, params.initial)
        mastery[observation.skill] = update_mastery(prior, observation.correct, params)
    return mastery


def select_next(
    candidates: Iterable[Candidate], mastery: dict[str, float], threshold: float = 0.8
) -> Candidate | None:
    pool = list(candidates)
    if not pool:
        return None

    def rank(candidate: Candidate) -> tuple[float, int, str]:
        levels = [mastery.get(skill, DEFAULT_PARAMETERS.initial) for skill in candidate.skills]
        distance = abs(min(levels, default=0.2) - threshold)
        return distance, candidate.difficulty, candidate.problem_id

    return min(pool, key=rank)


def hint_depth(skill_mastery: float, available_hints: int) -> int:
    if available_hints <= 0:
        return 0
    if skill_mastery < 0.35:
        return min(available_hints, 3)
    if skill_mastery < 0.7:
        return min(available_hints, 2)
    return 1
