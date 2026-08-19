# Modular Monolith Modernization Plan

## Summary

Replace the current prototype with a single FastAPI application composed of four internally isolated packages, backed by one PostgreSQL database with per-package schemas:

| Package | Sole ownership |
|---|---|
| `identity` | Accounts, credentials, sessions, and global roles |
| `learning` | Problems, classrooms, assignments, attempts, scoring, and progress |
| `modeling` | Skill tagging, mastery estimation, adaptive item selection, and hint policy |
| `tutoring` | Equation parsing, symbolic correctness, solution steps, and optional explanations |

Keep Streamlit as a temporary client. Apply DRY through single ownership of business rules and explicit package interfaces, not through a shared domain package. Enforce package boundaries mechanically with `import-linter` in CI rather than with network boundaries. Extract a service only when a measured driver appears.

```text
Streamlit (temporary client)
        ↓ HTTP
FastAPI application (single process)
   ├── identity/  → schema identity
   ├── learning/  → schema learning
   ├── modeling/  → schema learning
   └── tutoring/  → stateless
         ├── SymPy (authoritative)
         ├── Mathsteps (fallback, subprocess)
         └── LLM providers (optional)
```

### Why not three services

The project is an academic deliverable built by 2–3 people who all own all the code, with no real-student pilot. Every cross-service call in a service-oriented version of this system is synchronous and on the request critical path, so the split would add serialization, timeouts, retries, partial failure, and a client-generation pipeline while removing the ability to check an answer and award points in one transaction. Service boundaries would not map to team boundaries, so the coordination benefit that normally justifies that cost does not exist here. The ownership discipline the split was intended to enforce is obtained instead from package boundaries verified in CI.

## Architecture and Interfaces

### Package boundaries

#### `identity`

- Use `fastapi-users` for registration, password hashing, sessions, and reset flows rather than hand-rolled authentication.
- Own account lifecycle and global `student`/`teacher` roles.
- Expose a `current_user` dependency and role checks; expose nothing else.
- Do not implement custom cryptography, custom token formats, or a custom recovery policy.

#### `learning`

- Own all educational records and classroom-membership authorization.
- Start attempts, request hints, submit answers, award points, and derive progress.
- Store immutable attempt facts and snapshots of problem, scoring-policy, and solver versions.
- Never trust client-provided correctness, score, role, user ID, or hint count.
- Call `tutoring` and `modeling` in process, inside the same transaction as the attempt write.

#### `modeling`

- Own the learner model: skill (knowledge-component) tagging, mastery estimation, item selection, and hint policy.
- Use Bayesian Knowledge Tracing as the baseline mastery estimator.
- Replace random problem selection with mastery-driven selection.
- Read attempt history through a `learning` interface; never write educational records.

#### `tutoring`

- Remain stateless and own all mathematical decisions.
- Use SymPy as the authoritative parser and correctness engine.
- Parse user and problem input with `parse_expr` and a restricted `local_dict`; never `sympify` untrusted strings.
- Wrap Mathsteps with timeouts, return-code checks, output validation, and typed failures.
- Provide SymPy-native step generation for first-degree equations; keep Mathsteps only as a fallback.
- Keep LLM explanations optional and outside correctness and scoring.

### Package interfaces

Each package exposes exactly one interface module — `identity/api.py`, `learning/api.py`, `modeling/api.py`, `tutoring/api.py` — taking and returning DTOs. Nothing outside a package imports its ORM models, repositories, or internals.

Enforce with `import-linter` contracts in CI. This is the check that replaces the service split, and unlike a written convention it fails the build.

HTTP endpoints exposed to Streamlit:

- `POST /v1/auth/register`, `POST /v1/auth/login`, `POST /v1/auth/logout` (provided by `fastapi-users`)
- `GET /v1/problems`, `GET /v1/problems/next` (mastery-driven selection)
- `POST /v1/attempts`
- `POST /v1/attempts/{id}/hints`
- `POST /v1/attempts/{id}/submissions`
- `GET /v1/me/progress`
- CRUD endpoints for teacher-owned classrooms, memberships, and assignments

Standardize error envelopes with `code`, `message`, `request_id`, and optional field details. Require idempotency keys for attempt creation and answer submission.

### DRY rules

- Keep each business rule in exactly one owning package:
  - Mathematical equivalence belongs to `tutoring`.
  - Score calculation belongs to `learning`.
  - Mastery estimation and item selection belong to `modeling`.
  - Credential and session policy belongs to `identity`.
- Share only DTOs, error primitives, telemetry helpers, and test fixtures.
- Do not share ORM models, repositories, domain entities, or business-rule modules across packages.
- Avoid generic `utils` packages; promote code only after genuine repetition appears.
- Version DTOs at package boundaries so a later extraction is a transport change, not a redesign.

### Data and transactions

- Use one PostgreSQL database with separate `identity` and `learning` schemas.
- Allow foreign keys across schemas for `user_id`; referential integrity is worth more here than a speculative future split.
- Keep attempt creation, hint recording, submission, and score award in a single transaction.
- Derive progress from attempt records instead of mutable aggregate counters.
- Use no broker. Add events only when a concrete asynchronous consumer or scaling need emerges.
- Do not migrate anonymous cookie progress because it lacks trustworthy identity.
- Treat the attempt table as the research dataset: append-only, versioned, and directly analyzable.

## Known defects to fix first

**Correctness**

- `src/pages/main_page.py:111` — answer check is `solution - float(answer) <= 0.0001` with no `abs()`, so any answer larger than the solution is accepted. `float()` also raises on non-numeric input and rejects fractional answers. Compare symbolically.
- `src/pages/main_page.py:70` — `if hint_pos < len(steps)` is off by one; the next call indexes `steps[len]` and raises `IndexError`. Guard must be `< len(steps) - 1`.
- `src/pages/main_page.py:86` — score `5 * difficulty - (hint_pos + 1)` subtracts a point when no hint was used and goes negative on hard problems.
- `src/pages/main_page.py:85-89` — mutates `user_data` and never calls `save_data`; all progress from solving problems is discarded.
- `src/streamlit_app.py:26-35` — `save_data({})` runs before the `setdefault` calls, persisting an empty dict; `src/pages/profile.py:11` then raises `KeyError: 'resolvidos'`.
- Difficulty labels disagree: `streamlit_app.py:33` writes `"Intermediário"` while `main_page.py:81` and `problems.py:20` use `"Médio"`, raising `KeyError` on every medium solve.
- `src/solver.py:31` — `res[0]` raises `IndexError` when there is no solution and silently drops the infinite-solution case.
- `src/pages/main_page.py:59` — calls the solver with `current_problem == ""` on first load.
- `src/solver.py:8` — `'./ext/js/mathsteps/index.js'` is relative to the working directory.
- `src/solver.py:11` — `subprocess.run` with no `timeout` and no `returncode` check.

**Security**

- `src/solver.py:24-25` — `sympify` on user-controlled input evaluates arbitrary expressions.
- `src/pages/profile.py:22-26` — the manual-progress control lets any user grant themselves arbitrary points; cookie-stored progress is forgeable regardless.
- `.env` is tracked in Git; remove it from tracking and rotate anything it ever held.

**Hygiene**

- `requirements.txt` is unpinned, names `dotenv` instead of `python-dotenv`, omits `pandas` (used at `profile.py:2`), and declares unused `plotly`.
- `src/solver.py:6` — `from sympy import *` shadows builtins.
- `src/tools.py` is a dead stub; `src/app.py` is a superseded CLI demo.
- `src/pages/main_page.py:6` imports from `streamlit_app`, the navigation entrypoint, which is re-executed under `st.navigation`.

## Incremental Roadmap

### Phase 0 — Make it trustworthy

- Fix every defect listed above.
- Add pytest with a regression test per defect.
- Pin dependencies with a lockfile and add CI.
- Gate: the full suite passes with Node and Ollama absent, and no test depends on a cookie.

### Phase 1 — Modular monolith skeleton

- Stand up one FastAPI app with `identity`, `learning`, `modeling`, and `tutoring` packages.
- Add PostgreSQL, Alembic migrations, and per-package schemas.
- Seed problems from `src/pages/problems.py:7-44` into a real table with skill tags.
- Move scoring and correctness server-side; add `import-linter` contracts to CI.
- Gate: Streamlit computes no scores and stores no progress; a forged request cannot award points; a deliberate cross-package internal import fails the build.

### Phase 2 — Identity

- Wire `fastapi-users` for registration, login, sessions, and `student`/`teacher` roles.
- Key attempts to a real `user_id` from the first persisted row; add ownership checks to every learning record.
- Gate: cross-user authorization tests pass and no development-actor shim exists outside local configuration.

### Phase 3 — Learner model

- Tag problems with knowledge components (isolate variable, distribute, combine like terms, fractions).
- Implement per-learner per-skill mastery estimation using Bayesian Knowledge Tracing.
- Replace `random.randint` selection (`src/pages/problems.py:54`) with mastery-driven selection.
- Drive hint policy from the model instead of a fixed sequential walk through solver output.
- Build an evaluation harness that replays simulated or logged learners and compares adaptive against random selection.
- Gate: a reproducible experiment script produces the comparison table from stored attempt data.

### Phase 4 — Reduce Mathsteps risk

- Add SymPy-native step generation for the first-degree cases; keep Mathsteps behind the typed-failure wrapper as a fallback.
- Make degradation explicit: missing steps disable hints and never affect answer checking.
- Gate: hints work end to end with Node uninstalled.

### Phase 5 — Teacher workflows

- Add classrooms, memberships, assignments, teacher problem management, and reporting.
- Validate teacher-created equations through `tutoring` before activation.
- Preserve problem and policy versions for historical attempts.
- Gate: teachers access only owned classrooms and historical reports remain reproducible after problem edits.

### Phase 6 — Optional AI explanations

- Add Ollama and hosted adapters behind an `ExplanationProvider` port.
- Validate extracted equations through `tutoring` before use.
- Fall back to deterministic hints when AI is unavailable.
- Record provider, model, and prompt versions while minimizing retained student text.
- Gate: disabling the AI provider does not disrupt core learning journeys.

### Phase 7 — Operations, sized to reality

- One Dockerfile and one Compose file covering the app, PostgreSQL, and optional Ollama.
- Structured logs with request IDs, migrations on deploy, backups, and a tested restore.
- No gateway, TLS termination layer, tracing backend, or Kubernetes until a concrete need forces one.

### Phase 8 — Extract `tutoring`, only if measured

- Trigger conditions, fixed in advance: solver latency dominates request time under realistic load, or the solver requires independent scaling or a separate runtime.
- Because `tutoring/api.py` already speaks DTOs, extraction is a transport change.

## Learner Model

- **Knowledge components**: each problem is tagged with the skills it exercises; tags are versioned alongside the problem.
- **Mastery estimation**: Bayesian Knowledge Tracing per learner per skill, updated on every graded attempt, derived from immutable attempt records so estimates are recomputable.
- **Item selection**: choose the next problem by targeting skills near the mastery threshold rather than by uniform random draw.
- **Hint policy**: hint depth and content follow estimated mastery of the specific skill blocking the learner, not a fixed step index.
- **Recomputability**: every model output must be reproducible from the attempt table plus a model version, so results survive parameter changes.

## Research Evaluation

- **Baseline**: uniform random selection with sequential hints — the current prototype behavior.
- **Treatment**: mastery-driven selection with model-driven hints.
- **Measures**: attempts to mastery per skill, hint consumption per solved problem, and accuracy trajectory over a session.
- **Data**: the append-only attempt table with problem, policy, and solver version snapshots.
- **Reproducibility**: a single script regenerates all reported figures from stored data.

## Test Plan

- Unit-test symbolic equivalence, unsupported equations, scoring, hint penalties, role rules, mastery updates, and progress aggregation in their owning packages.
- Enforce package boundaries with `import-linter` contracts and assert a deliberate violation fails.
- Integration-test each package against the real database with schema separation verified.
- Test timeout, malformed output, unavailable Node or Ollama, invalid equations, no solution, and infinite solutions.
- Test idempotent attempt creation and submission under retries and concurrent requests.
- End-to-end test student and teacher journeys through the HTTP API.
- Security-test session expiry, revocation, role changes, classroom isolation, and forged identifiers and scores.
- Propagate and assert request IDs from Streamlit through the application.
- Test that mastery estimates are reproducible from stored attempts.

## Assumptions and Decisions

- DRY means single ownership of business rules plus explicit package interfaces, not one shared domain library.
- A modular monolith with CI-enforced package boundaries is preferred over three services; the split is deferred until a measured driver appears.
- Communication is in-process; there is no event broker and no internal HTTP.
- One PostgreSQL database with per-package schemas; cross-schema foreign keys are permitted for `user_id`.
- FastAPI is the application framework and Streamlit remains a temporary client.
- Authentication uses `fastapi-users`; custom authentication is explicitly out of scope. If a real pilot is approved, revisit with an identity provider rather than a hand-rolled implementation.
- SymPy remains authoritative; Mathsteps becomes a fallback rather than a permanent dependency; LLMs remain optional and outside correctness.
- The learner model is the research contribution and is planned, built, and evaluated as such.
- Evaluation is demo-only with no identifiable student data collected. Revisit under LGPD before any classroom pilot.
- Scale, availability, latency, and budget targets are undocumented; no capacity or improvement claims are assumed.
