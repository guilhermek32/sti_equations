import pytest

from sti_equations.modeling.api import Candidate, Observation, mastery_by_skill, select_next


def test_mastery_is_reproducible_and_reacts_to_evidence() -> None:
    history = [Observation("fractions", True), Observation("fractions", False)]
    first = mastery_by_skill(history)
    assert first == mastery_by_skill(history)
    assert first["fractions"] == pytest.approx(0.2842105263)


def test_selection_targets_skill_nearest_threshold() -> None:
    candidates = [
        Candidate("easy", ("isolate",), 1),
        Candidate("fraction", ("fractions",), 2),
    ]
    chosen = select_next(candidates, {"isolate": 0.95, "fractions": 0.7})
    assert chosen and chosen.problem_id == "fraction"


def test_selection_moves_on_from_mastered_skills() -> None:
    candidates = [
        Candidate("mastered", ("isolate",), 1),
        Candidate("learning", ("fractions",), 2),
    ]
    chosen = select_next(candidates, {"isolate": 0.81, "fractions": 0.2})
    assert chosen and chosen.problem_id == "learning"
