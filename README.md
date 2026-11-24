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

**Phase 2: orders and concurrency**

- [x] Order creation with server-side prices, required `Idempotency-Key`, and `201` with
      `Location`.
- [x] Order status state machine; invalid transitions return `409`.
- [x] Riders accept orders with an atomic conditional update: 20 concurrent riders, exactly one
      wins.
- [x] Dish of the day with limited units: 50 concurrent orders for the last unit create exactly
      one order.
- [x] Status changes with optimistic locking (`version`): a stale edit returns `409`.
- [x] The three concurrency strategies compared below.

**Phase 3: auth and web security**

- [x] Roles (customer, restaurant, rider) with `require_role`, and a table that says which role
      may make each status change.
- [x] Ownership checks: another user's order is a `404`, never a `403`.
- [x] Short-lived JWT access token (15 minutes) and an opaque refresh token (30 days), stored
      hashed, rotated on every use and revocable.
- [x] Refresh token reuse detection: a token used twice revokes its whole login, even when both
      uses arrive at the same time.
- [x] Logout and "log out everywhere".
- [x] Refresh token in an `HttpOnly`, `Secure`, `SameSite=Strict` cookie, with an `Origin` check
      against CSRF.
- [x] CORS restricted to the frontend's origin.

**Next phases**

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

Two optional settings control the browser side: `FRONTEND_ORIGIN` (default
`http://localhost:5173`) is the only origin allowed by CORS and by the CSRF check, and
`COOKIE_SECURE` (default `true`) marks the refresh cookie as HTTPS-only.

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

All endpoints live under `/v1`, except `/health`.

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Checks Postgres and Redis; `503` if either is down |
| `GET` | `/v1/restaurants` | List restaurants, including closed ones |
| `GET` | `/v1/restaurants/{id}` | One restaurant; `404` if it doesn't exist |
| `GET` | `/v1/restaurants/{id}/dishes` | A restaurant's menu; `404` if the restaurant doesn't exist |
| `POST` | `/v1/users` | Register; every new user is a customer |
| `POST` | `/v1/auth/token` | Log in: the access token in the body, the refresh token in an `HttpOnly` cookie |
| `POST` | `/v1/auth/refresh` | Trade the refresh cookie for a new access token and a new cookie; `401` if it's invalid, expired or reused |
| `POST` | `/v1/auth/logout` | End this login and clear the cookie |
| `POST` | `/v1/auth/logout-all` | End every login of the current user |
| `GET` | `/v1/users/me` | Current user |
| `GET` | `/v1/users`, `/v1/users/{id}` | Public user profiles |
| `PATCH` / `DELETE` | `/v1/users/{id}` | Update or delete your own user; `403` for anyone else's, whether the id exists or not |
| `POST` | `/v1/orders` | Customers place an order; requires `Idempotency-Key`. `409` if the restaurant is closed or a dish is unavailable or sold out |
| `GET` | `/v1/orders/{id}` | One of your orders; `404` for anyone else's |
| `PATCH` | `/v1/orders/{id}` | Change the status, sending the `version` you last saw. `404` if the order isn't yours, `403` if this step belongs to another role, `409` if it changed since or the transition isn't allowed |
| `POST` | `/v1/orders/{id}/accept` | Riders take an order that is paid or being prepared; `409` if another rider already took it |

`/v1/auth/refresh` and `/v1/auth/logout` read the refresh cookie, so they only accept requests
whose `Origin` is the frontend's (`403` otherwise).

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

### `Idempotency-Key` is required on `POST /orders`

A network error after the server created an order makes the client retry. Without protection that
retry creates a second order, and a second charge. The client sends an `Idempotency-Key` header,
generated once per checkout attempt and reused on every retry, and a retry with the same key
returns the original order.

- **It's required, not optional.** Public APIs such as Stripe make it optional for compatibility
  with clients that don't send it. Here the only clients are our own apps, so we'd rather reject a
  request without the header (`422`) than risk a duplicated, double-charged order.
- **Uniqueness is enforced by the database**, with `UNIQUE (customer_id, idempotency_key)`. Looking
  the key up before inserting isn't enough on its own: two simultaneous retries would both find
  nothing and both insert. The insert uses `ON CONFLICT DO NOTHING`, and the request that loses the
  race returns the order that won.
- **The key is scoped to the customer**, so one customer's key can never return another
  customer's order.
- **A retry returns the original order even if things changed since**, for example the restaurant
  closed. The key lookup runs before any validation.

### Order status is a state machine

```
pending → paid → preparing → on_the_way → delivered
   ↓        ↓
cancelled cancelled
```

The allowed transitions live in one table, `ALLOWED_TRANSITIONS` in `domain/order.py`, as plain
data. The service checks it and raises `409` for anything else. An order can't be cancelled once
the kitchen is preparing it, and `delivered` and `cancelled` are final. A test checks every pair of
statuses, so a transition added by mistake fails CI, and another one checks that every status has
an entry, so a new status can't be forgotten.

### Three concurrency strategies, and when to use each

The classic bug is *read, decide in Python, write*. Two requests read the same row, both decide
"yes", and both write: two riders get the same order, or the last unit is sold twice. Each case in
this project closes that gap with the strategy that fits it.

| Strategy | Where | How |
| --- | --- | --- |
| **Atomic conditional update** | Rider accepts an order; buying the dish of the day | The rule goes in the `WHERE`: `UPDATE orders SET rider_id = :rider WHERE id = :id AND rider_id IS NULL`. Postgres checks and writes in one step; no row updated means someone got there first |
| **Optimistic locking** | Changing an order's status (`PATCH`) | The client sends the `version` it last saw: `UPDATE ... WHERE id = :id AND version = :seen`, and every write does `version = version + 1`. Any change since then makes it fail |
| **Pessimistic locking** | Not in `main` (see below) | `SELECT ... FOR UPDATE` locks the row when it's read; everyone else waits until the commit |

**Atomic conditional update: when the rule fits in a `WHERE`.** "Is the order still free?" and
"are there enough units left?" are single conditions on the current row, so one statement both
checks and writes. It's the simplest and fastest option: one round trip, no lock held between
statements. `UPDATE ... RETURNING` gives back the updated row, so a single query covers the
happy path. A second query runs only on failure, to tell `404` (no such order) from `409` (taken).

**Optimistic locking: when a person decides based on what they saw.** A restaurant employee opens
an order at `paid`, and meanwhile a colleague moves it to `preparing` and a rider takes it. If the
first employee now cancels it, the transition `paid → cancelled` looks valid, but the decision was
made on stale data: a *lost update*. Only the client knows what it saw, so it sends the version.
The check spans the whole row: in one test the rider takes the order without changing its status,
and only the version catches it. Optimistic locking takes no locks, so it's the right choice when
conflicts are rare. On `409` the client reloads and shows the new state; it must not retry
automatically, or the stale decision goes through anyway.

The version is deliberately **not** required to accept an order. A rider doesn't care whether the
restaurant changed the status while they looked at the list, only whether the order is still free.
Requiring the version there would reject riders for unrelated changes.

**Pessimistic locking: when the decision doesn't fit in one statement.** Moving money between two
accounts, issuing invoice numbers without gaps, or anything that reads several rows and applies
logic SQL can't express. Its cost is that waiters each hold a database connection, so the
transaction must be short. A `SELECT ... FOR UPDATE` version of *accept* was built and passed the
same 20-rider test (without the lock, 7 riders won the same order). It isn't in `main` because the
atomic update does the same job in one query instead of two and holds the lock for less time.
`FOR UPDATE SKIP LOCKED` is the variant that matters most in practice: it's how a work queue hands
each worker a different row, and the natural fit for dispatching orders to riders automatically.

| | Atomic | Optimistic | Pessimistic |
| --- | --- | --- | --- |
| Protects | One condition at write time | Everything since the client last read | Everything between read and write |
| Window | Inside one request | Across requests (user think time) | Inside one request |
| Locks held | Only during the `UPDATE` | Only during the `UPDATE` | From the `SELECT` to the commit |
| Loser gets | `409` | `409`, then reloads | Waits, then usually `409` |
| Good for | Stock, quotas, first come first served | Edit forms, rare conflicts | Complex multi-row decisions, queues, frequent conflicts |

### Selling a limited dish

Dishes have a nullable `units_left`: `NULL` means unlimited, a number means the dish of the day. A
`CHECK (units_left >= 0)` constraint is the last line of defence: whatever the code does, the
database never stores negative stock.

- **The decrement is atomic:** `SET units_left = units_left - :qty WHERE units_left >= :qty`.
  Postgres computes the new value from the locked row. Computing it in Python would sell the last
  unit twice.
- **The stock is taken after the order is inserted.** If the dish is sold out, the exception rolls
  back the whole transaction, order included, so there is never an order without stock or stock
  taken without an order. Taking stock *before* the insert would leak units: a request that loses
  the idempotency race returns the existing order successfully, and the units it took would be
  committed for nothing.
- **A check before the insert** rejects requests for a dish already sold out without doing the
  insert. It reads a value that may be stale by the time it's used, so it's only a shortcut; the
  atomic `UPDATE` is what guarantees the result.
- **Rows are locked in `dish_id` order.** Two orders that lock the same dishes in different orders
  can deadlock, each waiting for the row the other holds. With a single global order no cycle can
  form.

### Slow calls never run inside a transaction

A transaction that waits on an external API keeps its row locks and its connection for as long as
the API takes, and a slow provider can exhaust the connection pool and take the whole API down.
Work that needs one is split into short transactions: reserve with an intermediate state (for
example `pending_payment`), call the API outside any transaction with an idempotency key, then
confirm or compensate in a second transaction. Phase 4 (payments) builds this.

### Roles and who may change an order

Every user has one role: `customer`, `restaurant` (staff of one restaurant) or `rider`.
Registration always creates a customer: the role never comes from the request body, or anyone
could sign up as staff. A `CHECK` constraint keeps the role and the restaurant consistent in both
directions: restaurant staff must have a restaurant, and nobody else may have one.

Endpoints that belong to one role say so in their signature (`CustomerUser`, `RiderUser`, built by
`require_role`). Status changes go through a single `PATCH` used by every role, so the rule lives
in a table in `domain/order.py`, next to the state machine:

| Change | Who |
| --- | --- |
| `pending → cancelled` | the customer who placed the order |
| `paid → preparing`, `paid → cancelled` | the restaurant of the order |
| `preparing → on_the_way`, `on_the_way → delivered` | the rider who accepted it |
| `pending → paid` | nobody through the API: the payment provider will confirm it (phase 4) |

The checks run in a fixed order, and each one protects something:

1. **Is the order yours?** If not, `404`. A `403` would confirm that the order exists, and anyone
   could enumerate ids (IDOR). "Yours" depends on the role: your purchase, your restaurant's
   order, or the delivery you accepted.
2. **Does the state machine allow the change?** If not, `409`, whoever asks.
3. **Is this step yours?** If not, `403`. You already know the order exists, so it reveals nothing.
4. **Is your version current?** If not, `409`. There's no point telling someone without
   permission to reload.

A test walks all 108 combinations of status, status and role against its own copy of the table,
so a permission added by mistake fails CI.

### Two tokens: a short access token and a revocable refresh token

| | Access token | Refresh token |
| --- | --- | --- |
| Format | JWT | Opaque random string |
| Lifetime | 15 minutes | 30 days |
| Travels in | the `Authorization` header | an `HttpOnly` cookie, only to `/v1/auth` |
| Checked by | its signature, without the database | a database lookup |
| Revocable | no, it just expires | yes |

A JWT can't be revoked: the server doesn't look it up, so a stolen one works until it expires. A
long-lived JWT would keep users logged in but make theft worse. Splitting the job gives both: the
access token is fast and expires quickly, and the refresh token is the one that controls the
session.

- **The refresh token is opaque, not a JWT.** It's only a key to a database row, and it's used
  once every 15 minutes, so the lookup is cheap. In exchange, it can be revoked.
- **It's stored as a SHA-256 hash.** A leaked database gives out nothing usable. A slow hash like
  bcrypt adds nothing here, because a 256-bit random token can't be guessed, and its random salt
  would make it impossible to find the row by hash.
- **It rotates.** Every refresh revokes the token it used and issues a new one, so each token
  works once.
- **Reuse revokes the whole login.** Every login starts a *family*, and rotated tokens inherit
  it. A used token coming back means someone has a copy, and there's no way to tell the owner from
  the thief, so every token of that family is revoked. Other logins of the same user keep working.
  Used tokens are marked `revoked_at` instead of deleted, because reuse can only be detected if
  the server remembers the token existed.
- **Two refreshes with the same token at the same time are a reuse too.** Both requests may read
  the token as unused, so the revocation is an atomic conditional update, the same pattern as a
  rider accepting an order: `UPDATE ... SET revoked_at = now() WHERE id = :id AND revoked_at IS
  NULL RETURNING id`. Only one request gets the row back. A test fires 20 concurrent refreshes and
  exactly one wins.
- **The revocation is committed before the `401`.** `get_db` rolls back when a request fails, and
  the `401` would undo the revocation together with it, leaving the thief logged in. A security
  write has to survive the error response. A test proves it against the real `get_db`.
- **Logout revokes the family**, so it ends the session even with an older token of it.
  "Log out everywhere" revokes every token of the user.
- **The trade-off:** after a logout, an access token already issued keeps working until it expires,
  15 minutes at most. Cutting it instantly would need a blocklist checked on every request.

### Where the tokens live: cookie vs localStorage

Anything in `localStorage` can be read by any script on the page, so a single XSS (a compromised
dependency, an unescaped field) can steal a 30-day session. The refresh token lives in an
`HttpOnly` cookie that no script can read, and the access token lives only in the frontend's
memory, where a stolen copy is worth 15 minutes.

The access token deliberately stays out of cookies. Sent in the `Authorization` header, it can't be
attached by another site, so the API's regular endpoints don't need CSRF protection at all. After a
page reload the frontend gets a new one from `/v1/auth/refresh`.

The cookie is `HttpOnly` (no script can read it), `Secure` (HTTPS only), `SameSite=Strict` (never
sent on a request started by another site) and scoped to `Path=/v1/auth` (not sent on every API
call). `set_cookie` and `delete_cookie` go through one helper each, because a cookie deleted with
a different path is a different cookie, and logout would silently leave it in place.

### CSRF: the cookie endpoints check `Origin`

Browsers attach cookies by themselves, whichever page starts the request. Another site can't read
the response, but it can still cause the effect: log the user out, or rotate their token so the
next legitimate refresh looks like a reuse. Two layers stop it:

1. `SameSite=Strict`, so the browser doesn't send the cookie on cross-site requests.
2. An `Origin` check on `/v1/auth/refresh` and `/v1/auth/logout`, the only endpoints that read the
   cookie. Browsers set `Origin` themselves and pages can't forge it, so anything other than the
   frontend's origin, or no `Origin` at all, gets a `403` before the token is touched. This also
   covers older browsers that ignore `SameSite`.

The check isn't applied where it adds nothing. `/v1/auth/logout-all` is authenticated by the
`Authorization` header, which another site can't add, so there's no CSRF without a cookie. Login
has no cookie to abuse, and checking `Origin` there would break the Swagger UI in `/docs`.

### CORS: the frontend is the only origin allowed to read responses

Browsers don't let a page read responses from another origin (the same-origin policy). The
frontend runs on a different origin than the API (another port locally, `app.` and `api.` in
production), so CORS opens one exception: `CORSMiddleware` allows exactly `FRONTEND_ORIGIN`, with
credentials, and exposes the `Location` and `X-Request-ID` headers to scripts.

- **Never `*` with credentials.** Browsers reject `*` on requests with cookies, so Starlette
  answers those by echoing back whatever `Origin` arrives, which would let any site read responses
  made with the user's cookies. A test fails if another origin ever gets the header.
- **CORS and CSRF use the same setting.** The `Origin` check stops other sites from *doing* things
  with the cookie; CORS decides who can *read* the responses. Defining the trusted origin once keeps
  them from disagreeing.

**Reproducing a CORS error.** A one-button page that calls `GET /v1/restaurants`, served on two
ports:

- From `http://localhost:5173`, the allowed origin, it shows the restaurants.
- From `http://localhost:5500` it fails with `TypeError: Failed to fetch`, and the console says
  *"blocked by CORS policy: No 'Access-Control-Allow-Origin' header is present"*. But the Network
  tab shows `200 OK`, and the server logs an ordinary `GET /v1/restaurants -> 200`.

The API answered; the browser received the response and refused to hand it to the page because the
header was missing. That's how a CORS error can come with a `200`, and why CORS doesn't protect an
API from attackers: it runs in the browser, `curl` ignores it, and the request is executed anyway.
What protects the API is authentication, `GET`s that never change anything, and CSRF checks where
cookies are involved.

One more trap showed up while reproducing it: an unhandled exception returns a `500` from the
outermost layer of the app, outside the CORS middleware, so it carries no CORS headers and the
browser reports it as a CORS error. When the console says CORS, check the server logs before the
CORS settings. Errors mapped by our exception handlers (`404`, `409`, ...) do carry the headers.

### The API is versioned in the URL

Every endpoint is under `/v1`. Mobile apps can't be force-updated, so old app versions keep calling
the API for months after a release. A breaking change (renaming or removing a field, changing a
type, making something required) ships as `/v2` while `/v1` keeps working. Additive changes (a new
endpoint, a new response field, a new optional parameter) don't need a new version.

The version goes in the URL rather than in a header because it's visible in every log line and
error, easy to call with `curl`, simple to route, and caches tell versions apart without extra
configuration. `/health` stays unversioned: load balancers and monitoring use it, not clients.

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

Concurrency tests (`tests/test_concurrency.py`) can't use that per-test transaction: on a single
connection, requests can't really run in parallel. They commit real data, fire the requests with
`asyncio.gather` through the real `get_db` so each one gets its own connection, and truncate the
tables afterwards. The rider and stock tests were run against a naive *read, check, write* version
of the code to prove they catch the race: 8 to 12 riders won the same order, and 24 to 29 orders
were created for 3 units. The race over a single unit is so narrow that the naive version sometimes
gets lucky, which is why the 3-unit test exists alongside the 1-unit one.

Some bugs only exist under concurrency. While building refresh tokens, `revoke` once used
`execute()` instead of `scalar()`: `execute()` never returns `None`, so every request believed it
had won. Every sequential test passed, because a token used twice in a row is caught earlier by its
`revoked_at`. Only the test with 20 simultaneous refreshes failed, with 3 winners.

Security rules are tested from both sides: the rule must allow what it should and reject what it
shouldn't. Where it matters, the test restates the rule instead of importing it (the role table,
the SHA-256 of the token), so the code isn't checked against itself. Each protection was also
removed on purpose to confirm a test fails: dropping the `Origin` check fails 4 tests, dropping
`HttpOnly` fails 1, and allowing `*` in CORS fails 2.

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
- Retry a transaction automatically when Postgres aborts it with a deadlock (`40P01`) or a
  serialization failure. Lock ordering prevents the deadlocks known today, but not ones caused by
  future code paths.
- Build the test schema by running the Alembic migrations instead of `create_all`. Today a
  migration missing something the model has (autogenerate doesn't detect new `CHECK` constraints)
  passes the tests.
- Send the order version as HTTP `ETag` / `If-Match` headers (`412 Precondition Failed`), the
  standard form of optimistic locking, instead of a field in the body.
- Accept a just-rotated refresh token for a few seconds (a grace period). Today two tabs that
  refresh at the same moment, or a retry after a lost response, look like a reuse and log the user
  out. The frontend can also avoid it by running a single refresh at a time.
- Delete expired refresh tokens with a periodic job. Logging in again without logging out leaves
  the previous family valid until it expires, even though no browser holds it.
- Store the user agent, IP and last use of each login, to list active sessions and end one of
  them.
- Log out everywhere automatically when the password changes.
- Create the restaurant staff and rider users in the seed. Registration only creates customers.

## Author

Alejandro

- GitHub: https://github.com/alejandrobodichon
