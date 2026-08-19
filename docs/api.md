# API Workflows

The interactive OpenAPI document at `/docs` is the authoritative endpoint and schema reference.
This guide shows the main request sequence. Examples assume the API is running on
`http://localhost:8000`.

## Errors and request IDs

Application errors use this envelope:

```json
{
  "code": "http_error",
  "message": "Problem not found",
  "request_id": "ce2fb516-c04e-47d4-aa62-f7d9f45926f9"
}
```

Validation failures may also include `details`. Send `X-Request-ID` to correlate a client action;
otherwise the API generates one. The response always returns the ID in the same header.

## Register and authenticate

Use a cookie jar so subsequent requests carry the database-backed session:

```bash
curl -i -c cookies.txt \
  -H 'Content-Type: application/json' \
  -d '{"email":"student@example.com","password":"password123"}' \
  http://localhost:8000/v1/auth/register

curl -i -c cookies.txt -b cookies.txt \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode 'username=student@example.com' \
  --data-urlencode 'password=password123' \
  http://localhost:8000/v1/auth/login
```

Registration always creates a student even if a role is included in the request. Log out and revoke
the current database session with:

```bash
curl -i -b cookies.txt -X POST http://localhost:8000/v1/auth/logout
```

## Complete a learner attempt

Select the next problem using the learner's current BKT mastery estimates:

```bash
curl -s -b cookies.txt http://localhost:8000/v1/problems/next
```

Start an attempt with the returned problem ID. Keep the same idempotency key when retrying the same
logical operation:

```bash
curl -s -b cookies.txt \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: attempt-001' \
  -d '{"problem_id":"PROBLEM_UUID"}' \
  http://localhost:8000/v1/attempts
```

The response includes `id` and the immutable problem snapshot. Use the attempt ID to request hints
or submit an answer:

```bash
curl -s -b cookies.txt -X POST \
  http://localhost:8000/v1/attempts/ATTEMPT_UUID/hints

curl -s -b cookies.txt \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: submission-001' \
  -d '{"answer":"1/2"}' \
  http://localhost:8000/v1/attempts/ATTEMPT_UUID/submissions
```

Answers may be integers, decimals, or fractions accepted by the restricted symbolic parser. The
server ignores client-supplied correctness or point fields. A correct submission earns
`max(0, 5 * difficulty - hints_used)` points.

Fetch derived progress or an optional explanation with:

```bash
curl -s -b cookies.txt http://localhost:8000/v1/me/progress
curl -s -b cookies.txt -X POST \
  http://localhost:8000/v1/attempts/ATTEMPT_UUID/explanation
```

## Teacher endpoints

Teacher endpoints return `403` for students. Public registration cannot provision this role.

| Method and path | Purpose |
|---|---|
| `POST /v1/problems` | Validate and create a teacher-owned problem |
| `PATCH /v1/problems/{problem_id}` | Update an owned problem and increment its version |
| `DELETE /v1/problems/{problem_id}` | Deactivate an owned problem |
| `GET /v1/classrooms` | List active owned classrooms |
| `POST /v1/classrooms` | Create a classroom |
| `PATCH /v1/classrooms/{classroom_id}` | Rename an owned classroom |
| `DELETE /v1/classrooms/{classroom_id}` | Deactivate an owned classroom |
| `GET/POST /v1/classrooms/{id}/memberships` | List or add student memberships |
| `DELETE /v1/classrooms/{id}/memberships/{membership_id}` | Remove a membership |
| `GET/POST /v1/classrooms/{id}/assignments` | List or create assignments |
| `DELETE /v1/classrooms/{id}/assignments/{assignment_id}` | Delete an assignment |
| `GET /v1/classrooms/{id}/report` | Aggregate submissions and points for current members |

Ownership failures use `404` instead of revealing whether another teacher's resource exists.
