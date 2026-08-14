import uvicorn


def run_api() -> None:
    uvicorn.run("sti_equations.app:app", host="0.0.0.0", port=8000)
