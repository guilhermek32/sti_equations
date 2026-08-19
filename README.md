# STI Equations

STI Equations is an adaptive tutor for first-degree equations. It combines deterministic symbolic
mathematics with a Bayesian Knowledge Tracing (BKT) learner model and optional local-model
explanations.

The application is a FastAPI modular monolith. Correctness, hints, scoring, progress, and
authorization are server-side; Streamlit is a temporary HTTP client and stores no educational
records.

## What is included

- Symbolic parsing and answer checking with SymPy.
- Native step-by-step hints that work without Node or an LLM.
- Mastery-driven problem selection and hint depth.
- Cookie-based student authentication with database-backed, revocable sessions.
- Idempotent attempt creation and answer submission.
- Teacher-owned classrooms, memberships, assignments, problem management, and reports.
- Immutable problem snapshots for reproducible grading and historical progress.
- A deterministic simulation harness comparing adaptive and random policies.
- Optional OpenAI-compatible llama.cpp explanations with deterministic fallback.

## Quick start

Prerequisites are Python 3.11 or newer and
[uv](https://docs.astral.sh/uv/getting-started/installation/). Node, Mathsteps, Ollama, and
PostgreSQL are not required for local development or tests.

Install all runtime and development dependencies:

```bash
uv sync --all-groups
```

Start the API:

```bash
uv run sti-api
```

In another terminal, start the client:

```bash
uv run streamlit run src/streamlit_app.py
```

Open <http://localhost:8501>. API documentation is available at
<http://localhost:8000/docs>, and `GET /health` provides a lightweight health check.

The default configuration uses `sti.db`, creates its tables on startup, and seeds the problem
catalog. Public registration always creates a student account. Teacher roles are deliberately not
self-assignable and currently must be provisioned directly by a trusted operator; teacher
workflows are exposed through the API, not the Streamlit client.

## Configuration

Settings use the `STI_` prefix and can be placed in `.env.local`. Do not commit that file.

| Variable | Default | Purpose |
|---|---|---|
| `STI_DATABASE_URL` | `sqlite+aiosqlite:///./sti.db` | SQLAlchemy async database URL |
| `STI_AUTH_SECRET` | development-only value | Reset and verification token secret; replace outside development |
| `STI_COOKIE_SECURE` | `false` | Send session cookies only over HTTPS |
| `STI_AUTO_CREATE_DATABASE` | `true` | Create tables at API startup; disable when Alembic owns migrations |
| `STI_EXPLANATION_URL` | unset | Base URL of an OpenAI-compatible inference server |
| `STI_EXPLANATION_MODEL` | `local-model` | Model identifier sent to the inference server |
| `STI_API_URL` | `http://127.0.0.1:8000` | API URL used by the Streamlit process |

Use a long, random `STI_AUTH_SECRET` and set `STI_COOKIE_SECURE=true` behind HTTPS in production.
`STI_AUTO_CREATE_DATABASE=false` is the expected deployment setting because the container runs
Alembic before starting the API.

## Quality gates

Run the same checks used in CI:

```bash
uv run ruff format --check src tests migrations
uv run ruff check src tests migrations
uv run lint-imports --no-cache
uv run pytest -q
```

The suite does not require browser cookies, Node, Mathsteps, Ollama, or llama.cpp. Import Linter
enforces the internal package boundaries.

## PostgreSQL deployment

Copy the example configuration and replace its development credentials:

```bash
cp .env.example .env.local
docker compose --env-file .env.local up --build
```

Compose uses `.env.local` for variable interpolation, starts PostgreSQL, applies the Alembic
migration, then exposes the API on port 8000 and Streamlit on port 8501. PostgreSQL uses separate
`identity` and `learning` schemas. Keep `STI_COOKIE_SECURE=false` for this plain-HTTP local Compose
setup; enable it when the application is served through HTTPS.

Back up and restore the database with:

```bash
scripts/backup.sh backup.dump
scripts/restore.sh backup.dump
```

Restore uses `pg_restore --clean --if-exists` and replaces matching database objects. Test the
procedure against a disposable environment before relying on it for recovery.

## Optional explanations

Core tutoring never depends on generated text. Any server implementing the OpenAI-compatible
`/v1/chat/completions` API can supply explanations. For llama.cpp:

```bash
llama-server -m /path/to/model.gguf --host 127.0.0.1 --port 8081
STI_EXPLANATION_URL=http://127.0.0.1:8081 \
STI_EXPLANATION_MODEL=your-model-name \
uv run sti-api
```

The Compose `ai` profile starts an Ollama server only; it does not download a model or enable
explanations automatically. Pull a model, set an OpenAI-compatible base URL reachable from the app
container (for example `http://ollama:11434`), and set the matching model name before starting the
profile.

Provider errors fall back to native deterministic hints and never affect answer correctness or
points.

## Evaluation

Generate the deterministic learner-policy artifacts:

```bash
uv run sti-evaluate --output artifacts/evaluation
```

Add `--llama-url http://127.0.0.1:8081` to evaluate an available explanation provider, or
`--attempt-export path/to/anonymized.csv` to summarize an anonymized attempt export. Generated
artifacts include comparison data, trajectories, and run metadata.

The simulation evaluates model behavior; it is not evidence of classroom learning outcomes. See
[the evaluation report](docs/evaluation.md) for the recorded run and limitations.

## Documentation

- [Architecture and invariants](docs/architecture.md)
- [API workflows and examples](docs/api.md)
- [Reproducible evaluation](docs/evaluation.md)
- [Modernization plan and decisions](plan.md)

Before collecting data from real learners, define retention and consent policies and revisit the
data model under Brazil's LGPD.
