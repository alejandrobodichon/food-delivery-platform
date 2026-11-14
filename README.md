# Food Delivery Platform

A food delivery backend built as an interview portfolio project. Each phase adds one area
(orders and concurrency, auth, payments, async work, performance, a React frontend, an AI
support agent) and documents the decisions behind it.

[![CI](https://github.com/alejandrobodichon/food-delivery-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/alejandrobodichon/food-delivery-platform/actions/workflows/ci.yml) [![Coverage Status](https://coveralls.io/repos/github/alejandrobodichon/food-delivery-platform/badge.svg?branch=main)](https://coveralls.io/github/alejandrobodichon/food-delivery-platform?branch=main)

## Table of contents

- [Features](#features)
- [Technology](#technology)
- [Prerequisites](#prerequisites)
- [Running it](#running-it)
- [API](#api)
- [Architecture](#architecture)
- [Design decisions](#design-decisions)
- [Things to improve](#things-to-improve)
- [Author](#author)

## Features

**Phase 1: backend foundation**

- [x] Restaurant and dish catalog, with an idempotent seed.
- [x] User registration and login with a JWT access token.
- [x] Health check for Postgres and Redis.
- [x] JSON logs with a correlation id per request.
- [x] Infrastructure errors translated into domain errors and mapped to HTTP status codes.
- [x] CI with lint, format, type checking, tests and coverage.

**Next phases**

- [ ] Orders and concurrency: idempotent order creation, atomic rider assignment, optimistic
      locking.
- [ ] Auth and web security: refresh tokens, cookies, CSRF, roles, ownership checks.
- [ ] Deploy.
- [ ] Payments and webhooks, background jobs, performance and caching, a React frontend, an AI
      support agent, security scanning, and load testing.

## Technology

- Language: Python 3.14
- Framework: FastAPI
- Database: PostgreSQL, SQLAlchemy 2.0 (async), Alembic
- Cache and queues: Redis
- Package manager: uv
- Tests: pytest
- Lint and types: ruff, mypy
- Containers: Docker, Docker Compose
- CI: GitHub Actions

## Prerequisites

- Docker and Docker Compose.
- `make` (preinstalled on macOS and Linux).
- [uv](https://docs.astral.sh/uv/), to run the API or the tests outside Docker.
- Ports 8000, 5432 and 6379 free on localhost.

## Running it

### With Docker

Create a `.env` file in the project root with a secret key:

```bash
echo "SECRET_KEY=$(openssl rand -hex 32)" > .env
```

Start everything (Postgres, Redis, migrations and the API):

```bash
make up
```

The API is at http://localhost:8000 and the interactive docs at http://localhost:8000/docs.

### Locally

Start only the databases:

```bash
docker compose up -d db redis
```

Then, from `api/`:

```bash
cp .env.example .env
uv sync
uv run alembic upgrade head
uv run python -m scripts.seed
uv run fastapi dev main.py
```

### Tests

From `api/`, with Postgres running (tests use a separate `test_delivery` database):

```bash
uv run pytest
```

Or fully isolated in Docker, from the project root:

```bash
make test
```

CI runs ruff, mypy and pytest on every push and pull request.

## API

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Checks Postgres and Redis; `503` if either is down |
| `GET` | `/restaurants` | List restaurants, including closed ones |
| `GET` | `/restaurants/{id}` | One restaurant; `404` if it doesn't exist |
| `GET` | `/restaurants/{id}/dishes` | A restaurant's menu; `404` if the restaurant doesn't exist |
| `POST` | `/users` | Register |
| `POST` | `/auth/token` | Log in, returns a JWT |
| `GET` | `/users/me` | Current user |
| `GET` | `/users`, `/users/{id}` | Public user profiles |
| `PATCH` / `DELETE` | `/users/{id}` | Update or delete your own user; `403` for anyone else's, whether the id exists or not |

## Architecture

```
router  →  service  →  repository  →  database
(HTTP)     (rules)     (queries)
```

- **Routers** handle HTTP only: parse the request, call a service, declare the response schema.
- **Services** hold business rules, such as "a missing restaurant is a 404, an empty menu is not".
- **Repositories** are the only layer that talks to SQLAlchemy.

Errors flow the same way. Infrastructure errors are translated into domain errors at the
repository boundary (`raise DatabaseUnavailable() from e`), and a single mapping in
`core/error_handlers.py` turns each domain error into an HTTP status. Services and routers
never see SQLAlchemy exceptions.

## Design decisions

### Three kinds of models

| Kind | Where | Job |
| --- | --- | --- |
| Pydantic schemas | `schemas/` | The API contract: what comes in and what goes out |
| SQLAlchemy models | `models/` | How data is stored |
| Domain dataclasses | `domain/` | What the business logic works with |

They change for different reasons. Adding a database column must not expose it in the API, and
renaming a JSON field must not require a migration. The response schema is also a security
boundary: the `User` model has a `password_hash`, and the response schema simply has no field
for it. A test asserts the exact set of fields returned, so a new internal field can't leak by
accident.

### Money is stored as integer cents

Prices are `price_cents: int`, never `float`. Floats are binary and can't represent most decimal
amounts exactly (`0.1 + 0.2 != 0.3`). Integer cents are exact, and they're also what payment
providers use (minor units). `Numeric(10, 2)` would work in Postgres, but it becomes a float as
soon as it's serialized to JSON for a JavaScript client.

### No defaults for `is_open` and `is_available`

Both columns are `NOT NULL` with no default, so whoever creates a restaurant or a dish has to
decide. Any default would be a silent guess, and the wrong guess is costly in both directions:
`True` can sell from a closed restaurant, `False` hides a restaurant that's actually open.

### Constraints live in the database

- **Restaurant names are unique** (`uq_restaurants_name`). An application-level "does it exist?"
  check has a race: two concurrent requests can both see "no" and both insert. Only a database
  constraint prevents that. Branches of a chain get distinct names.
- **Dish names are unique per restaurant** (`uq_dishes_restaurant_id_name`). This constraint also
  creates the index for `WHERE restaurant_id = ?`. Postgres doesn't index foreign keys
  automatically, and this composite index already covers that lookup by the leftmost-prefix rule.

### The seed is a script, not a migration

Migrations run in every environment, production included. Demo data doesn't belong there. The
seed (`scripts/seed.py`) is idempotent: it uses `INSERT ... ON CONFLICT DO NOTHING` on the unique
constraints, so running it twice changes nothing.

### Resource lifecycles

- **App lifetime** (`lifespan`): the database engine and the Redis client are pools shared by every
  request. They're created once at startup and closed at shutdown.
- **Request lifetime** (`get_db`): each request gets its own session. It commits if the endpoint
  succeeds and rolls back if it raises. A test proves the rollback.

`transaction()` is the same commit-or-rollback logic as an async context manager, used by code
that runs outside a request, such as the seed script.

### Users can only change their own account

`PATCH` and `DELETE` on `/users/{id}` return `403` when the id isn't yours, **whether that id
exists or not**. Returning `404` for missing ids would let anyone enumerate which ids exist by
comparing responses. The user always comes from the token, never from the request body.

### Observability

- Every log line is JSON and carries a **correlation id**. A middleware reads `X-Request-ID` (or
  generates one), stores it in a `ContextVar`, and returns it in the response. All logs from one
  request can be found by that id.
- Repository calls are wrapped in `@timed`, which logs their duration. In production this would be
  replaced by OpenTelemetry tracing, which measures every query without decorating anything.

### Testing

Tests run against a real Postgres, not SQLite or mocks, so constraints and SQL behave exactly as in
production. Each test runs inside a transaction that is rolled back, so tests don't see each
other's data. A guard in `conftest.py` refuses to run if the database name doesn't start with
`test_`, so a misconfigured environment can never drop development tables.

External dependencies are replaced with fakes through `app.dependency_overrides`, for example a
`FakeRedis` that simulates Redis being down.

### Deployment-ready containers

- Migrations run in a dedicated `migrate` service. The API only starts after it finishes
  successfully, so the app never runs against an outdated schema.
- The Docker image is multi-stage: dependencies are installed in a build stage from the locked
  `uv.lock`, and the final image runs as a non-root user.
- The container starts the server with `exec`, so it receives `SIGTERM` directly and shuts down
  cleanly, running the `lifespan` cleanup.

## Things to improve

- Run tests against [testcontainers](https://testcontainers.com/) instead of a database started
  by hand, so the test setup is fully automatic.
- Translate database errors raised by `commit()` too. Today only repository queries are
  translated to `503`; a connection lost between the query and the commit still returns `500`.
- Replace `@timed` log lines with OpenTelemetry tracing and metrics.

## Author

Alejandro

- GitHub: https://github.com/alejandrobodichon
