# Architecture and Invariants

## System shape

STI Equations is one FastAPI process split into four internally isolated packages:

```text
Streamlit client
      |
      | HTTP + session cookie
      v
FastAPI application
  |-- identity  -> users and database-backed access tokens
  |-- learning  -> problems, attempts, progress, and teacher workflows
  |-- modeling  -> BKT mastery, item selection, and hint policy
  `-- tutoring  -> parsing, equivalence, solving, hints, and explanations
      |
      `-- PostgreSQL: identity and learning schemas
```

SQLite maps both database schemas to its default namespace for local development and tests.
PostgreSQL retains the physical schema separation.

Each package exposes an `api.py` interface. Other packages must not import its ORM models or
implementation details. The contracts in `.importlinter` enforce these boundaries in CI.

## Ownership

| Decision or data | Owner |
|---|---|
| Credentials, sessions, and global roles | `identity` |
| Attempts, hints, submissions, scores, and classrooms | `learning` |
| Mastery updates, adaptive selection, and hint depth | `modeling` |
| Equation validity, symbolic equivalence, and solution steps | `tutoring` |

The Streamlit client may display results but does not decide correctness, calculate points, choose
a user ID, or persist progress.

## Attempt lifecycle

1. The authenticated learner requests an active problem.
2. `POST /v1/attempts` stores the learner ID and an immutable problem snapshot.
3. Hint requests use the snapshotted equation and skills plus mastery derived from prior attempts.
4. Submissions are checked symbolically and scored inside `learning`.
5. Progress is derived from submissions and attempt snapshots rather than mutable counters.

The snapshot contains the equation, variable, difficulty, skills, and problem version. Editing a
problem after an attempt starts therefore cannot change that attempt's correct answer, score,
mastery observations, hints, explanation context, or historical difficulty bucket.

Attempt creation and submission require caller-generated idempotency keys. The database uniqueness
constraints are the final defense against duplicate writes during retries or concurrent requests.

## Trust boundaries

- Authentication comes from a database-backed session cookie. Logout deletes the access token;
  expired tokens are rejected.
- Public registration ignores privileged role input and always creates a student.
- Attempt access is restricted to the authenticated owner.
- Classroom and teacher-created problem mutations are restricted to the owning teacher.
- Mathematical input is parsed through a restricted SymPy parser. Generated explanations are never
  used for correctness or scoring.
- Request IDs are accepted through `X-Request-ID`, generated when absent, returned in the response,
  and included in structured request logs.

## Data and migrations

`identity` owns `user` and `access_token`. `learning` owns problems, attempts, hint records,
submissions, explanation records, classrooms, memberships, and assignments. Foreign keys are used
across schemas because this is a single transactional system.

The initial Alembic migration creates both PostgreSQL schemas and all registered tables. Deployment
uses migrations with automatic table creation disabled. Local SQLite startup favors convenience and
creates tables automatically.

## Deliberate limitations

- The Streamlit interface covers the learner journey only; teacher workflows currently require API
  access.
- Teacher provisioning has no public endpoint and requires a trusted operational process.
- Reports represent current classroom membership and stored submissions; this is not yet a complete
  learning-management or audit system.
- Explanations are optional best-effort output from a local or hosted compatible provider.
- No broker, gateway, distributed tracing stack, or separate tutoring service is justified by the
  current scale. Extraction triggers are documented in `plan.md`.
