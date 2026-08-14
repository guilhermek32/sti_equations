from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from sympy import Eq, Poly, S, expand, solve
from sympy.core.expr import Expr
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

if TYPE_CHECKING:
    from .api import Hint, Solution, StepProvider


class EquationError(ValueError):
    """Base error for invalid or unsupported equations."""


class UnsafeExpression(EquationError):
    pass


class UnsupportedEquation(EquationError):
    pass


class StepProviderError(RuntimeError):
    pass


_TRANSFORMS = standard_transformations + (convert_xor, implicit_multiplication_application)
_FORBIDDEN = {"__", "[", "]", "{", "}", ";", ":", "'", '"', "."}


def _parse(text: str, variable: str) -> Expr:
    from sympy import Symbol

    if not text.strip() or any(token in text for token in _FORBIDDEN):
        raise UnsafeExpression("expression contains forbidden syntax")
    if not variable.isalpha() or len(variable) != 1:
        raise UnsafeExpression("variable must be one letter")
    symbol = Symbol(variable, real=True)
    try:
        expression = parse_expr(
            text,
            local_dict={variable: symbol},
            global_dict={
                "Integer": __import__("sympy").Integer,
                "Float": __import__("sympy").Float,
                "Rational": __import__("sympy").Rational,
                "Symbol": Symbol,
            },
            transformations=_TRANSFORMS,
            evaluate=True,
        )
    except (SyntaxError, TypeError, ValueError) as exc:
        raise UnsafeExpression("invalid mathematical expression") from exc
    if not isinstance(expression, Expr) or expression.free_symbols - {symbol}:
        raise UnsafeExpression("only numeric expressions and the declared variable are allowed")
    return expression


def _equation(equation: str, variable: str) -> tuple[Expr, Expr]:
    if equation.count("=") != 1:
        raise EquationError("an equation must contain exactly one equals sign")
    left, right = equation.split("=", 1)
    return _parse(left, variable), _parse(right, variable)


class EquationEngine:
    def __init__(self, fallback: StepProvider | None = None) -> None:
        self._fallback = fallback

    def solve(self, equation: str, variable: str) -> Solution:
        from .api import Solution, SolutionKind

        left, right = _equation(equation, variable)
        symbol = next(iter(left.free_symbols | right.free_symbols), None)
        if symbol is None:
            return Solution(SolutionKind.INFINITE if left == right else SolutionKind.NONE)
        try:
            polynomial = Poly(expand(left - right), symbol)
        except Exception as exc:
            raise UnsupportedEquation("only polynomial equations are supported") from exc
        if polynomial.degree() > 1:
            raise UnsupportedEquation("only first-degree equations are supported")
        if polynomial.is_zero:
            return Solution(SolutionKind.INFINITE)
        results = solve(Eq(left, right), symbol)
        if not results:
            return Solution(SolutionKind.NONE)
        if results == [S.ComplexInfinity]:
            return Solution(SolutionKind.NONE)
        return Solution(SolutionKind.UNIQUE, str(results[0]))

    def is_equivalent_answer(self, equation: str, variable: str, answer: str) -> bool:
        solution = self.solve(equation, variable)
        from .api import SolutionKind

        if solution.kind is not SolutionKind.UNIQUE:
            return False
        candidate = _parse(answer, variable)
        if candidate.free_symbols:
            return False
        expected = _parse(solution.value or "", variable)
        return bool((candidate - expected).equals(0))

    def steps(self, equation: str, variable: str) -> list[Hint]:
        from .api import Hint, SolutionKind

        left, right = _equation(equation, variable)
        solution = self.solve(equation, variable)
        if solution.kind is not SolutionKind.UNIQUE:
            return []
        symbol = next(iter(left.free_symbols | right.free_symbols))
        expression = expand(left - right)
        polynomial = Poly(expression, symbol)
        coefficient, constant = polynomial.all_coeffs()
        hints: list[Hint] = []
        if left != expand(left) or right != expand(right):
            hints.append(
                Hint(
                    "Aplique a propriedade distributiva e simplifique os dois lados.",
                    "distribute",
                )
            )
        if len(left.as_ordered_terms()) > 2 or len(right.as_ordered_terms()) > 2:
            hints.append(Hint("Agrupe os termos semelhantes.", "combine_like_terms"))
        if constant:
            hints.append(
                Hint(
                    f"Mova o termo constante para obter {coefficient}*{variable} = {-constant}.",
                    "isolate_variable",
                )
            )
        if coefficient != 1:
            hints.append(Hint(f"Divida os dois lados por {coefficient}.", "fractions"))
        hints.append(
            Hint(
                f"Confira substituindo {variable} = {solution.value} na equação original.",
                "isolate_variable",
            )
        )
        if hints:
            return hints
        if self._fallback:
            try:
                return self._fallback.steps(equation, variable)
            except StepProviderError:
                return []
        return []


class MathstepsFallback:
    _TEXT = {
        "ADD_TO_BOTH_SIDES": "Adicione o mesmo valor aos dois lados.",
        "SUBTRACT_FROM_BOTH_SIDES": "Subtraia o mesmo valor dos dois lados.",
        "DIVIDE_FROM_BOTH_SIDES": "Divida os dois lados pelo mesmo valor.",
        "COLLECT_AND_COMBINE_LIKE_TERMS": "Agrupe os termos semelhantes.",
    }

    def __init__(self, script: Path, timeout: float = 2.0) -> None:
        self._script = script
        self._timeout = timeout

    def steps(self, equation: str, variable: str) -> list[Hint]:
        from .api import Hint

        if not self._script.is_file():
            raise StepProviderError("Mathsteps script is unavailable")
        try:
            result = subprocess.run(
                ["node", str(self._script), equation],
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise StepProviderError("Mathsteps did not complete") from exc
        if result.returncode != 0:
            raise StepProviderError("Mathsteps returned an error")
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise StepProviderError("Mathsteps returned malformed output") from exc
        if not isinstance(payload, list):
            raise StepProviderError("Mathsteps output must be a list")
        return [
            Hint(self._TEXT[item["changeType"]], "isolate_variable")
            for item in payload
            if isinstance(item, dict) and item.get("changeType") in self._TEXT
        ]
