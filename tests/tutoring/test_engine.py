import pytest

from sti_equations.tutoring.api import SolutionKind, TutoringService
from sti_equations.tutoring.engine import UnsafeExpression, UnsupportedEquation


@pytest.fixture
def service() -> TutoringService:
    return TutoringService()


def test_symbolic_fraction_and_oversized_answer(service: TutoringService) -> None:
    assert service.is_equivalent_answer("2*x + 1 = 2", "x", "1/2")
    assert not service.is_equivalent_answer("2*x + 1 = 2", "x", "100")


def test_rejects_code_and_non_numeric_answers(service: TutoringService) -> None:
    with pytest.raises(UnsafeExpression):
        service.is_equivalent_answer("x = 1", "x", "__import__('os')")
    with pytest.raises(UnsafeExpression):
        service.is_equivalent_answer("x = 1", "x", "banana")


def test_distinguishes_no_and_infinite_solutions(service: TutoringService) -> None:
    assert service.solve("x = x + 1", "x").kind is SolutionKind.NONE
    assert service.solve("2*x + 2 = 2*(x + 1)", "x").kind is SolutionKind.INFINITE


def test_rejects_non_linear_equation(service: TutoringService) -> None:
    with pytest.raises(UnsupportedEquation):
        service.solve("x^2 = 4", "x")


def test_native_hints_need_no_node(service: TutoringService) -> None:
    hints = service.hints("2*(x + 1) = 8", "x")
    assert hints
    assert hints[-1].text.endswith("equação original.")
