import csv

from sti_equations.evaluation import run_experiment, summarize_attempt_export


def test_experiment_is_reproducible_and_compares_policies() -> None:
    first, trajectories = run_experiment(learners=10, seed=42)
    second, _ = run_experiment(learners=10, seed=42)
    assert first == second
    assert {result.policy for result in first} == {"random", "adaptive"}
    assert trajectories
    assert all(0 <= result.accuracy <= 1 for result in first)


def test_attempt_export_replay(tmp_path) -> None:
    source = tmp_path / "attempts.csv"
    with source.open("w", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=["model_version", "correct", "hint_count"])
        writer.writeheader()
        writer.writerows(
            [
                {"model_version": "bkt-v1", "correct": "true", "hint_count": "1"},
                {"model_version": "bkt-v1", "correct": "false", "hint_count": "2"},
            ]
        )
    assert summarize_attempt_export(source) == [
        {"model_version": "bkt-v1", "attempts": 2, "accuracy": 0.5, "hints_per_attempt": 1.5}
    ]
