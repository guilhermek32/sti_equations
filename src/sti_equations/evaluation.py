from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx

from .learning.api import problem_catalog
from .modeling.api import BKTParameters, Candidate, select_next, update_mastery
from .tutoring.api import LlamaCppExplanationProvider, default_service

SKILLS = ("isolate_variable", "distribute", "combine_like_terms", "fractions")


@dataclass(frozen=True)
class PolicyResult:
    policy: str
    attempts_to_mastery: float
    hints_per_solved: float
    accuracy: float
    learners: int
    seed: int


def _problem_candidates() -> list[Candidate]:
    return [
        Candidate(str(index), tuple(skills), difficulty)
        for index, (_, _, difficulty, skills) in enumerate(problem_catalog())
    ]


def _simulate_policy(policy: str, learners: int, seed: int) -> tuple[PolicyResult, list[dict]]:
    rng = random.Random(f"{seed}:{policy}")
    candidates = _problem_candidates()
    total_attempts = total_hints = total_solved = total_correct = 0
    trajectories: list[dict] = []
    attempts_to_mastery: list[int] = []
    params = BKTParameters()
    for learner in range(learners):
        estimated = {skill: params.initial for skill in SKILLS}
        latent = {skill: rng.uniform(0.1, 0.35) for skill in SKILLS}
        mastered_at: int | None = None
        for attempt_number in range(1, 81):
            if policy == "adaptive":
                candidate = select_next(candidates, estimated)
                assert candidate is not None
            else:
                candidate = rng.choice(candidates)
            weakest = min(candidate.skills, key=lambda skill: latent.get(skill, 0.2))
            probability = 0.12 + 0.8 * latent.get(weakest, 0.2)
            correct = rng.random() < probability
            hints = (
                (3 if estimated.get(weakest, 0.2) < 0.35 else 2)
                if policy == "adaptive"
                else min(3, 1 + int(not correct))
            )
            for skill in candidate.skills:
                estimated[skill] = update_mastery(estimated.get(skill, params.initial), correct)
                latent[skill] = min(0.995, latent.get(skill, 0.2) + (0.07 if correct else 0.035))
            total_attempts += 1
            total_hints += hints
            total_correct += int(correct)
            total_solved += int(correct)
            trajectories.append(
                {
                    "policy": policy,
                    "learner": learner,
                    "attempt": attempt_number,
                    "correct": int(correct),
                    "mean_mastery": sum(estimated.values()) / len(estimated),
                }
            )
            if min(estimated.values()) >= 0.8:
                mastered_at = attempt_number
                break
        attempts_to_mastery.append(mastered_at or 80)
    result = PolicyResult(
        policy=policy,
        attempts_to_mastery=statistics.mean(attempts_to_mastery),
        hints_per_solved=total_hints / max(total_solved, 1),
        accuracy=total_correct / total_attempts,
        learners=learners,
        seed=seed,
    )
    return result, trajectories


def run_experiment(
    learners: int = 200, seed: int = 20260814
) -> tuple[list[PolicyResult], list[dict]]:
    results: list[PolicyResult] = []
    trajectories: list[dict] = []
    for policy in ("random", "adaptive"):
        result, policy_trajectories = _simulate_policy(policy, learners, seed)
        results.append(result)
        trajectories.extend(policy_trajectories)
    return results, trajectories


def summarize_attempt_export(path: Path) -> list[dict]:
    """Summarize an anonymized attempt-table export grouped by recorded model version."""
    groups: dict[str, list[dict]] = {}
    with path.open(newline="", encoding="utf-8") as source:
        for row in csv.DictReader(source):
            groups.setdefault(row["model_version"], []).append(row)
    return [
        {
            "model_version": model,
            "attempts": len(rows),
            "accuracy": sum(row["correct"].lower() in {"1", "true", "yes"} for row in rows)
            / len(rows),
            "hints_per_attempt": sum(int(row["hint_count"]) for row in rows) / len(rows),
        }
        for model, rows in sorted(groups.items())
        if rows
    ]


async def evaluate_llama(base_url: str, model: str, case_count: int = 5) -> list[dict]:
    service = default_service()
    provider = LlamaCppExplanationProvider(base_url, model, timeout=120)
    cases = problem_catalog()[::7][:case_count]
    results = []
    for equation, variable, difficulty, _skills in cases:
        hints = service.hints(equation, variable)
        started = time.perf_counter()
        try:
            explanation = await provider.explain(equation, hints)
            solution = service.solve(equation, variable)
            valid = bool(explanation.text) and bool(
                solution.value and solution.value in explanation.text
            )
            error = None
        except (httpx.HTTPError, RuntimeError) as exc:
            explanation = None
            valid = False
            error = type(exc).__name__
        results.append(
            {
                "equation": equation,
                "difficulty": difficulty,
                "model": model,
                "prompt_version": LlamaCppExplanationProvider.PROMPT_VERSION,
                "latency_seconds": round(time.perf_counter() - started, 3),
                "valid": valid,
                "error": error,
                "response": explanation.text if explanation else None,
            }
        )
    return results


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Reproduce adaptive tutor evaluation artifacts")
    parser.add_argument("--output", type=Path, default=Path("artifacts/evaluation"))
    parser.add_argument("--learners", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20260814)
    parser.add_argument("--attempt-export", type=Path)
    parser.add_argument("--llama-url")
    parser.add_argument("--llama-model", default="local-model")
    parser.add_argument("--llama-cases", type=int, default=5)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    comparison, trajectories = run_experiment(args.learners, args.seed)
    _write_csv(args.output / "comparison.csv", [asdict(result) for result in comparison])
    _write_csv(args.output / "trajectories.csv", trajectories)
    metadata = {
        "seed": args.seed,
        "learners": args.learners,
        "model_version": "bkt-v1",
        "source": "simulated",
    }
    if args.attempt_export:
        empirical = summarize_attempt_export(args.attempt_export)
        _write_csv(args.output / "attempt_replay.csv", empirical)
        metadata["attempt_export"] = str(args.attempt_export)
    if args.llama_url:
        import asyncio

        llama_results = asyncio.run(
            evaluate_llama(args.llama_url, args.llama_model, args.llama_cases)
        )
        (args.output / "llama_evaluation.json").write_text(
            json.dumps(llama_results, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    (args.output / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
