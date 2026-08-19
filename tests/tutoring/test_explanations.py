import pytest

from sti_equations.tutoring.api import Hint, LlamaCppExplanationProvider, deterministic_explanation


def test_deterministic_explanation_is_explicit_fallback() -> None:
    result = deterministic_explanation([Hint("Divida os dois lados por 2.", "fractions")])
    assert result.fallback
    assert result.provider == "deterministic"
    assert result.text == "Divida os dois lados por 2."


@pytest.mark.asyncio
async def test_llama_cpp_rejects_malformed_output(monkeypatch) -> None:
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": []}

    class Client:
        def __init__(self, **kwargs):
            del kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            del args

        async def post(self, *args, **kwargs):
            del args, kwargs
            return Response()

    monkeypatch.setattr("sti_equations.tutoring.api.httpx.AsyncClient", Client)
    provider = LlamaCppExplanationProvider("http://localhost:8081", "test")
    with pytest.raises(RuntimeError, match="malformed"):
        await provider.explain("x = 1", [Hint("Isole x.", "isolate_variable")])
