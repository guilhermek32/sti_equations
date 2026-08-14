# STI Equations

An adaptive tutor for first-degree equations. The application is a FastAPI modular monolith with
four internal packages: `identity`, `learning`, `modeling`, and `tutoring`. Streamlit is an HTTP-only
temporary client; correctness, hints, scoring, progress, and authorization live on the server.

## Local development

Python dependencies are managed exclusively with [uv](https://docs.astral.sh/uv/):

```bash
uv sync --all-groups
uv run sti-api
```

In a second terminal:

```bash
uv run streamlit run src/streamlit_app.py
```

The default development database is SQLite. It is created and seeded on startup. PostgreSQL is the
deployment database and uses separate `identity` and `learning` schemas.

Run the quality gates with:

```bash
uv run ruff check src tests migrations
uv run lint-imports --no-cache
uv run pytest -q
```

The tests do not require Node, Mathsteps, Ollama, llama.cpp, or browser cookies. SymPy is authoritative
for parsing and correctness, and native first-degree hints keep tutoring available without Node.

## PostgreSQL deployment

Copy `.env.example` to `.env.local`, set a strong `STI_AUTH_SECRET`, then run:

```bash
docker compose up --build
```

The app container runs `alembic upgrade head` before starting. The API is at port 8000 and Streamlit
at port 8501. The optional Ollama profile is started with `docker compose --profile ai up`; explanations
remain non-critical and fall back to deterministic hints.

Back up and restore the PostgreSQL database with:

```bash
scripts/backup.sh backup.dump
scripts/restore.sh backup.dump
```

## llama.cpp explanations and evaluation

Any OpenAI-compatible llama.cpp server can provide optional explanations. For example:

```bash
llama-server -m /path/to/model.gguf --host 0.0.0.0 --port 8081
STI_EXPLANATION_URL=http://127.0.0.1:8081 uv run sti-api
```

The reproducible learner-policy experiment and optional explanation evaluation are run with:

```bash
uv run sti-evaluate --output artifacts/evaluation
uv run sti-evaluate --output artifacts/evaluation --llama-url http://127.0.0.1:8081
```

No identifiable learner data is collected by the evaluation harness. Revisit the data model and
retention policy under LGPD before a real classroom pilot.

## API

The OpenAPI document is available at `/docs`. The main routes are registration/login/logout,
problem listing and adaptive selection, idempotent attempts and submissions, model-driven hints,
derived progress, optional explanations, and teacher-owned classrooms, memberships, assignments,
and problem creation. Error responses include `code`, `message`, and `request_id`.

See [plan.md](plan.md) for the architectural decisions, extraction triggers, and research design.
