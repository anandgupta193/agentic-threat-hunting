# APPROACH: AI Threat-Hunting Query Generator + Credit-Limited API

> How the system is designed, built, evaluated and improved.
> Design-choice references such as **D4** point to the full decision log in [`DECISIONS.md`](DECISIONS.md).

## Table of Contents
1. [Context & Focus](#1-context--focus)
2. [Data Findings](#2-data-findings)
3. [Key Design Decisions](#3-key-design-decisions)
4. [Module Architecture](#4-module-architecture)
5. [DB Schema](#5-db-schema)
6. [API Contracts](#6-api-contracts)
7. [Business Logic & Edge Cases](#7-business-logic--edge-cases)
8. [Generation Harness](#8-generation-harness)
9. [Evaluation Harness](#9-evaluation-harness)
10. [Performance](#10-performance)
11. [Logging, Errors & Config](#11-logging-errors--config)
12. [Testing](#12-testing)
13. [Build Phases](#13-build-phases)
14. [Prompting Strategy](#14-prompting-strategy)
15. [Iteration Log](#15-iteration-log)
16. [Challenges & Solutions](#16-challenges--solutions)
17. [Limitations](#17-limitations)
18. [Future Scope](#18-future-scope)

---

## 1. Context & Focus
The system has three jobs:
- **Generate queries:** convert plain-English threat-hunting hypotheses into DuckDB SQL over CloudTrail logs, and explain each query (interpretation, reasoning, assumptions, confidence).
- **Evaluate:** score generated results against a provided answer key, then iterate on the prompt and show before/after metrics.
- **Meter credits:** every LLM call spends a per-user token budget (200K per fixed 6h UTC window), stored in a database and exposed through a FastAPI HTTP API.

**Design focus: where this document goes deepest**
| Area | Where |
|---|---|
| Harness (generation pipeline + evaluation runner) | §8, §9 |
| DB schema | §5 |
| APIs | §6 |
| Business logic (credits, admission, query rules, edge cases) | §7 |

**Out of scope for this version:** multi-instance deployment, orchestration beyond docker-compose, parallel evaluation. See §18.

**Existing assets**
| File | Use |
|---|---|
| `nineteenFeaturesDf.csv` | Log dataset required by the brief (1.04GB, 1,939,207 records, 19 columns; 7 records span two lines) |
| `hypotheses.json` | 11 hypotheses (ids 1–8, 9a, 9b, 10) |
| `hypotheses_outcomes.json` | Answer key, a pandas-style dict per hypothesis |
| `utils.py::load_hypotheses_outcomes` | Reused by the evaluator to load the answer key |

---

## 2. Data Findings
We use `nineteenFeaturesDf.csv`, as the brief requires (D7). An earlier draft used `dec12_18features.csv`, a coarsened copy with month-only times, 2-octet IPs and first-token user agents, which could not match the answer key. That approach was dropped.

**Verified against the answer key**
- **Same row order.** The answer key's index values are 0-based row positions in this CSV. All 78 expected rows checked for hypotheses 1, 2, 3 and 6 match on `eventTime` and `sourceIPAddress`.
- **Full fidelity.** Timestamps are ISO-8601 to the second (`2017-02-12T19:57:06Z`), IPs are complete, and user agents are full strings.
- **The user-agent keywords the hypotheses need are present:**

  | Keyword | Rows |
  |---|---|
  | `kali` | 96,578 |
  | `parrot` | 53,250 |
  | `powershell` | 7,102 |
  | `command/` | 3,047 |

- **Nulls are empty cells,** which become `NaN` in pandas and `NULL` in DuckDB, the same as in the answer key. Examples: `errorCode` is empty in 431,493 rows, `userIdentityuserName` in 110,185, `requestParametersinstanceType` in 616,170.

**Data quirks the evaluator and schema card must handle**
| Quirk | Example | Handling |
|---|---|---|
| Numeric-looking IDs stored as floats | `userIdentityaccountId = 811596193553.0`, `eventVersion = 1.05` | Cast to text consistently on both sides before comparing |
| Some user agents wrapped in brackets | `[S3Console/0.4]`, `[Boto3/... Resource]` | Keep as-is; tell the LLM in the schema card so `LIKE` patterns account for it |
| Masked values | `userIdentityuserName = HIDDEN_DUE_TO_SECURITY_REASONS` | Document in the schema card |
| Timestamps are strings | `2017-05-17T23:23:34Z` | Kept as text, exactly as in the CSV (D36); the schema card tells the LLM to use `CAST(eventTime AS TIMESTAMP)` for time filters |
| Hypothesis wording vs. real values | #4 says `UnauthorizedOperation`; the real value is `Client.UnauthorizedOperation` (351,760 rows); `AccessDeniedException` (1,165) exists next to `AccessDenied` | Full value lists in the schema card + the zero-row value check (§8.2) |

**Column cardinality (drives the schema card, §8.2)**

Distinct non-NULL values, measured on the built `cloudtrail.duckdb`. 118 answer-key rows (hypotheses 1, 2, 3, 6, 10) were checked cell by cell against `rowid`, with 0 mismatches.
| Column | Distinct values |
|---|---|
| `userIdentitytype` | 5 |
| `eventType` | 4 |
| `awsRegion` | 17 |
| `userIdentityarn` | 57 |
| `errorCode` | 103 |
| `eventSource` | 164 |
| `requestParametersinstanceType` | 170 |
| `eventName` | 1,242 |
| `userAgent` | 8,811 |
| `sourceIPAddress` | 9,402 |

**Hypothesis shapes (all fully answerable on this dataset)**
| ID | Expected shape |
|---|---|
| 1 | 12 rows, selected columns |
| 2 | 61 rows, all columns |
| 3 | 4 rows |
| 4 | 2,387 groups (eventName, arn, count) |
| 5 | 4,767 groups (arn, ip, ua, count) |
| 6 | 1 row |
| 7 | 34 groups (instanceType, count) |
| 8 | 212 groups (arn, ip, ua, errorCode, count) |
| 9a | 1,896 groups (arn, ua, count) |
| 9b | 101 groups (ua, count) |
| 10 | 40 rows |

---

## 3. Key Design Decisions
The full log, with alternatives considered and superseded choices, is in [`DECISIONS.md`](DECISIONS.md).

| Area | Choice | Why |
|---|---|---|
| Service | FastAPI, fully async; modular monolith (D1, D5) | Clear module boundaries without the operational cost of microservices |
| Credit store | Postgres 16 in Docker; SQLAlchemy 2.0 async ORM over `asyncpg`; hand-written `schema.sql` (D2, D15, D16) | Per-user row locks make admission concurrency-safe; usage survives restarts; schema readable in one file |
| Audit | `query_requests` table: one row per API request, linked to its LLM calls (D17) | Every request is traceable: what it did, what it cost, how it ended |
| Log engine | DuckDB embedded; native `cloudtrail.duckdb` file built once by a `data-prep` service; the LLM sees a 19-column all-text view (D3, D7, D36, D39) | Fast columnar scans of 1.9M events; `SELECT *` matches the original data exactly |
| SQL safety | Allowlist validator + locked-down DuckDB (read-only, no external access, configuration locked) (D41) | Defence in depth around untrusted LLM-written SQL |
| Query quality | Static schema card with real values + a zero-row value check that triggers self-correction (D33) | Catches value traps such as `UnauthorizedOperation` vs `Client.UnauthorizedOperation` without extra tool calls |
| Confidence | Computed deterministically by the harness from objective signals, with reasons (D34) | Explainable and repeatable; LLM self-ratings are poorly calibrated |
| LLM | Claude Sonnet 5.5 with schema-constrained structured output and a fixed effort level; prompts as versioned files; provider switch: Anthropic API, OpenRouter, or local Claude Code CLI (D6, D27, D44) | Strong SQL generation; guaranteed explanation fields; runs with an API key or a Claude subscription |
| Overspend | Let the call finish, block the next; in-flight claim at admission (D4) | Concurrent calls can't both spend the last credits; overshoot ≤ one call |
| Windows | Fixed UTC blocks; a call counts in the window it was admitted in (D10, D11) | Exact 00/06/12/18 boundaries; no split accounting |
| Retries | Every self-correction attempt is metered and re-admitted (D12) | Every LLM call spends credits, as the brief requires |
| Evaluation | Strict scoring only; two runs (before/after) over real HTTP; sequential; timestamped run folders; replay; fresh user per run (D18–D21, D29, D30, D38, D40) | Honest, reproducible before/after comparison |
| Iteration policy | Prompt changes may only add rules that hold for any hypothesis; answer-key quirks are explained, not fitted (D29) | No overfitting to the 11 test hypotheses |
| Integrity | The answer key is never shown to the LLM (D8) | Honest evaluation |

---

## 4. Module Architecture
```
Client ─► Middleware (request-id, timing, access log, gzip)
       ─► Guards (X-User-Id → 401/404/403; DTO validation → 422)        ← early exits
       ─► Controller (HTTP only: DTO in → service → DTO out)
       ─► Services (business logic, no HTTP)
            ├─ UserService
            ├─ CreditService  ── admit() / finalize()   ── CreditRepository  ─► Postgres (Docker)
            ├─ QueryService   ── GenerationHarness (§8)  ── QueryRepository   ─► Postgres (Docker)
            │                     ├ LLMGateway (Anthropic | Fake)
            │                     ├ SqlValidator (sqlglot allowlist)
            │                     ├ DuckDBExecutor (read-only, no external access, timeout, to_thread)
            │                     └ ConfidenceScorer (deterministic signals)
            └─ (offline) EvaluationHarness (§9), used by main.py through the HTTP API
```

### Folder layout
```
app/
  main.py                 # app factory + lifespan (DB, DuckDB, schema card, LLM client)
  core/
    config.py             # pydantic-settings; reads .env; validated at startup
    logging.py            # structlog JSON; contextvars (request_id, user_id)
    errors.py             # AppError hierarchy + handlers → ErrorResponse
    middleware.py         # request-id, timing, access log
    clock.py              # injectable Clock (enables window tests)
  common/
    guards.py             # require_user, require_self
  db/
    engine.py             # async engine + pool (asyncpg), apply schema.sql at startup
    base.py               # DeclarativeBase + naming conventions
  modules/
    users/        controller.py  service.py  repository.py  dtos.py  models.py (User)
    credits/      controller.py  service.py  repository.py  dtos.py  models.py (TokenUsage)  policy.py (pure rules, §7)
    queries/      controller.py  service.py  repository.py  dtos.py  models.py (QueryRequest)
    harness/      pipeline.py  stages.py  trace.py  confidence.py   (§8)
    llm/          types.py (LLMGateway protocol)  anthropic_gateway.py  openrouter_gateway.py  claude_code_gateway.py  fake_gateway.py  factory.py  prompt_registry.py
    query_engine/ schema_card.py  validator.py  allowlist.py  executor.py  value_check.py
evaluation/
  runner.py  scorer.py  normalizers.py  metrics.py  report.py  loaders.py (wraps utils.py)
prompts/                  # all LLM prompts live here as files, never inside Python code (§8.1)
  v1/  system.md  user_template.md  retry_template.md
  v2/  system.md  user_template.md  retry_template.md
schema.sql
scripts/prepare_data.py   # CSV → data/cloudtrail.duckdb (run by the data-prep service; skips if up to date)
data/                     # nineteenFeaturesDf.csv (placed by you, gitignored) + cloudtrail.duckdb (generated)
runs/                     # one timestamped folder per evaluation run (§9)
tests/ unit/  integration/  live/ (opt-in, real Claude)
api.py  main.py  query_generator.py  evaluator.py   # thin root entry points named as in the brief
Dockerfile  docker-compose.yml  .env.example  pyproject.toml  Makefile
```

### Local runtime (docker-compose, D26)
The project ships its **own** Postgres in its own `docker-compose.yml`, isolated from any other database on the machine. Everything is driven by `.env`, so an evaluator only copies `.env.example`, adds an API key and runs.

| Service | Image | Purpose |
|---|---|---|
| `db` | `postgres:16-alpine` | Credit store. Named volume `threat_hunt_pgdata`; healthcheck via `pg_isready`; published on host port `${POSTGRES_PORT}` (default **5433**, so it can't clash with a Postgres already on 5432); an init script creates the `${POSTGRES_TEST_DB}` database for tests |
| `data-prep` | built from `Dockerfile` | One-time job (D39): converts `data/nineteenFeaturesDf.csv` into `data/cloudtrail.duckdb`, then exits. Skips the work if the stored CSV hash matches. A missing CSV fails with a clear message and the Kaggle link |
| `api` | built from `Dockerfile` | FastAPI + embedded DuckDB. Mounts `./data` read-only. `depends_on: db (healthy)` and `data-prep (completed successfully)`. Inside the compose network it reaches the DB at `db:5432` (compose overrides `POSTGRES_HOST`/`POSTGRES_PORT` for this service) |

- `COMPOSE_PROJECT_NAME=threat-hunt` keeps container, network and volume names unique to this project.
- **Evaluator quick start:**
  ```bash
  # 1. download nineteenFeaturesDf.csv from Kaggle into ./data/
  cp .env.example .env        # 2. set ANTHROPIC_API_KEY; change ports/passwords if needed
  make up                     # 3. docker compose up -d (db → data-prep → api)
  python main.py              # 4. full evaluation over HTTP against the running API
  ```
- `make db-up` starts only Postgres, so you can run the API locally with `uvicorn` for the fastest dev loop. `make prepare-data` runs the conversion without Docker.
- **Bring your own Postgres:** skip the compose `db` service and set `DATABASE_URL` in `.env`. The API creates its tables there at startup from `schema.sql`.
- Tests use the separate `${POSTGRES_TEST_DB}` database in the same container; tables are truncated between tests.

**Layering rules**
- Controllers never touch the DB; services never touch HTTP; repositories hold all SQL.
- DTOs (`dtos.py`, Pydantic) are separate from ORM models (`models.py`). ORM objects never leave the repository/service layer; controllers only see DTOs.
- **ORM usage rules:** `schema.sql` is the source of truth and the ORM models mirror it (no `create_all`). Sessions use `expire_on_commit=False`; relationships are `lazy="raise"`, so every load is explicit (`selectinload`) and no hidden queries run in async code. Hot paths (the window sum, the admission lock) use explicit `select()` statements: `select(User).where(...).with_for_update()`.
- Modules depend on each other's **services**, never on their repositories.
- The LLM, DuckDB and clock sit behind small interfaces (`Protocol`), so tests can swap in fakes.
- Business rules that need no I/O live in pure functions (`credits/policy.py`) and are unit-tested directly.

---

## 5. DB Schema
Postgres 16. All timestamps are `TIMESTAMPTZ`, stored in UTC.

```sql
CREATE TABLE IF NOT EXISTS users (
  user_id      VARCHAR(64) PRIMARY KEY CHECK (user_id ~ '^[A-Za-z0-9_.-]{1,64}$'),
  token_limit  INTEGER     NOT NULL CHECK (token_limit > 0),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per POST /v1/queries that reached the credit check (audit trail)
CREATE TABLE IF NOT EXISTS query_requests (
  request_id      VARCHAR(40)  PRIMARY KEY,
  user_id         VARCHAR(64)  NOT NULL REFERENCES users(user_id),
  hypothesis      TEXT         NOT NULL,
  status          VARCHAR(16)  NOT NULL CHECK (status IN ('in_progress','succeeded','failed','rejected')),
  error_code      VARCHAR(40),                 -- e.g. CREDITS_EXHAUSTED, SQL_INVALID, LLM_TIMEOUT
  final_sql       TEXT,
  confidence      NUMERIC(3,2) CHECK (confidence BETWEEN 0 AND 1),
  row_count       INTEGER      CHECK (row_count >= 0),
  attempts        SMALLINT     NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  prompt_version  VARCHAR(16),
  prompt_hash     CHAR(12),                    -- first 12 hex chars of the prompt files' SHA-256
  model           VARCHAR(64),
  latency_ms      INTEGER,
  created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  completed_at    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_qr_user_created ON query_requests (user_id, created_at DESC);

-- One row per LLM call (brief minimum + status/attempt/model)
CREATE TABLE IF NOT EXISTS token_usage (
  id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id        VARCHAR(64) NOT NULL REFERENCES users(user_id),
  request_id     VARCHAR(40) NOT NULL REFERENCES query_requests(request_id),
  attempt        SMALLINT    NOT NULL CHECK (attempt >= 1),
  input_tokens   INTEGER     NOT NULL DEFAULT 0 CHECK (input_tokens  >= 0),
  output_tokens  INTEGER     NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
  window_start   TIMESTAMPTZ NOT NULL,
  status         VARCHAR(16) NOT NULL CHECK (status IN ('pending','completed','failed','expired')),
  model          VARCHAR(64),
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at   TIMESTAMPTZ,
  UNIQUE (request_id, attempt)
);
CREATE INDEX IF NOT EXISTS ix_tu_user_window ON token_usage (user_id, window_start)
  INCLUDE (input_tokens, output_tokens, status);
```

**Design notes**
- **`window_start` is stored on each row.** "Tokens used this window" becomes an indexed lookup on `(user_id, window_start)`, with no date math in the query and no full scan.
- **`status` on `token_usage`** supports the in-flight claim (`pending`), crash recovery (`expired`) and failed calls (`failed`).
- **`UNIQUE(request_id, attempt)`** stops the same LLM call from being recorded twice.
- **CHECK constraints** reject negative tokens, non-positive limits, bad user IDs and unknown statuses at the DB level. This is a second line of defence behind the DTO validation.
- **`query_requests` vs `token_usage`:** a request is the business unit, and an LLM call is the billing unit. One request can contain up to `1 + MAX_SELF_CORRECT` calls.
- **Covering index** (`INCLUDE`): the hot query is answered from the index alone (index-only scan).
- **Hot query:**
  ```sql
  SELECT COALESCE(SUM(input_tokens + output_tokens), 0)  AS used,
         COUNT(*) FILTER (WHERE status = 'pending')      AS in_flight
  FROM token_usage
  WHERE user_id = :uid AND window_start = :ws;
  ```
- **Locking:** admission locks only that user's row (`SELECT … FROM users WHERE user_id = :uid FOR NO KEY UPDATE`, D46). Different users never block each other, the same user's admissions run one at a time, and FK checks from concurrent inserts are not blocked.

---

## 6. API Contracts
**Conventions**
- JSON in and out.
- Every response echoes `X-Request-Id`, taken from the client or generated.
- Every error uses one envelope:
  ```json
  { "error": { "code": "CREDITS_EXHAUSTED", "message": "…", "details": {} }, "request_id": "req_…" }
  ```

### `POST /v1/users`: create a user (no `X-User-Id` needed, D23)
```json
// request
{ "user_id": "analyst-1", "token_limit": 50000 }      // both optional
// 201
{ "user_id": "analyst-1", "token_limit": 50000, "created_at": "2026-10-29T10:12:00Z" }
```
- 409 `USER_EXISTS`
- 422 invalid `user_id` (allowed: `[A-Za-z0-9_.-]{1,64}`) or `token_limit` (must be from 1 to `MAX_TOKEN_LIMIT`)

### `POST /v1/queries`: generate and run a query (header `X-User-Id`)
```json
// request
{ "hypothesis": "Root user console login attempts can be identified in CloudTrail logs",
  "title": "Root Access Through Console",              // optional (D32)
  "include_results": true,                             // optional, default true (D31)
  "max_rows": 5000 }                                   // optional, ≤ MAX_RESULT_ROWS
// 200
{
  "request_id": "req_8f2…",
  "status": "succeeded",                               // or "failed" (D22)
  "query": { "sql": "SELECT … FROM cloudtrail WHERE …", "dialect": "duckdb" },
  "explanation": {
    "interpretation": "This hypothesis is asking for…",
    "reasoning": "I structured the query this way because…",
    "assumptions": ["Root means userIdentitytype = 'Root'", "…"],
    "confidence": 0.85,                                // computed by the harness (D34)
    "confidence_reasons": ["valid on first attempt", "all filter values exist in the data",
                           "1 assumption made (-0.05)", "…"],
    "result_summary": "61 rows · 9 distinct sourceIPAddress · eventTime 2017-02-12 → 2020-01-15"
  },
  "result": { "columns": ["eventTime", "…"], "rows": [["…"]], "row_count": 61,
              "total_rows": 61, "truncated": false },   // null when include_results = false
  "trace": { "attempts": [ { "attempt": 1, "input_tokens": 3120, "output_tokens": 410,
                             "latency_ms": 4200, "outcome": "ok", "error": null } ],
             "stage_ms": { "generate": 4200, "validate": 3, "execute": 180 },
             "total_ms": 4420 },
  "usage": { "tokens_used": 3530, "tokens_remaining": 196470,
             "window_start": "2026-10-29T06:00:00Z", "resets_at": "2026-10-29T12:00:00Z" }
}
```

**Also in the response:** `explanation.output_kind`; `error` (`{code, message}` when `status` is `failed`, e.g. `SELF_CORRECTION_EXHAUSTED`, `CREDITS_EXHAUSTED_MIDWAY`, `QUERY_TIMEOUT`); and `prompt` (`{version, hash, model}`). `query.sql` is the query as written, without the internal row cap. `usage.tokens_remaining` is read when the response is built, so it reflects every call billed so far in the window.

**Request rules**
- `hypothesis`: required, 5–2000 chars after trimming. `title`: optional, ≤ 200 chars. There is no `id` field, so the generator can't contain answer-key-specific logic (D32).
- `include_results`: the harness **always** executes the SQL internally (needed for self-correction). This flag only controls whether rows are returned. With `false`, the response carries the validated SQL, explanation, summary and usage (D31).
- `max_rows`: caps the returned rows; `total_rows` always gives the true count.

### `GET /v1/users/{user_id}/credits` (header `X-User-Id` must match the path)
```json
{ "user_id": "analyst-1", "token_limit": 200000, "tokens_used": 3530,
  "tokens_remaining": 196470, "in_flight": 0,
  "window_start": "2026-10-29T06:00:00Z", "resets_at": "2026-10-29T12:00:00Z" }
```

### `GET /v1/users/{user_id}/usage`: LLM calls in the current window
```json
{ "user_id": "analyst-1", "window_start": "…", "resets_at": "…",
  "totals": { "calls": 2, "input_tokens": 6100, "output_tokens": 830, "total_tokens": 6930 },
  "calls": [ { "request_id": "req_8f2…", "attempt": 1, "input_tokens": 3120,
               "output_tokens": 410, "total_tokens": 3530, "status": "completed",
               "model": "claude-sonnet-5-5", "created_at": "…" } ] }
```

### `GET /healthz`
Returns 200 when the DB and DuckDB are reachable.

### 429 response (from `POST /v1/queries`)
```
HTTP/1.1 429   Retry-After: 6120
{ "error": { "code": "CREDITS_EXHAUSTED", "message": "Token budget exhausted for this window",
             "details": { "tokens_remaining": 0, "resets_at": "2026-10-29T12:00:00Z" } },
  "request_id": "req_…" }
```
`CREDITS_CONTENDED` returns the same shape with a short `Retry-After` (§7.3).

### Status-code matrix
| Code | When | Endpoints |
|---|---|---|
| 200 | OK, including a generation that failed after retries (`status: "failed"`) | queries, credits, usage |
| 201 | User created | users |
| 400 | Malformed `X-User-Id` | all guarded |
| 401 | `X-User-Id` missing or blank | all guarded |
| 403 | Header user ≠ path user | credits, usage |
| 404 | Unknown user | all guarded |
| 409 | User already exists | users |
| 422 | Body validation failed | users, queries |
| 429 | Credits exhausted or contended (LLM not called) | queries |
| 502 | LLM provider error after SDK retries | queries |
| 504 | LLM or DuckDB timed out | queries |
| 500 | Unexpected error (logged with request_id; no internals leaked) | all |

---

## 7. Business Logic & Edge Cases

### 7.1 Pure rules (`credits/policy.py`, no I/O)
```python
window_bounds(now, window_hours) -> (window_start, resets_at)
remaining(limit, used) -> max(0, limit - used)
decide_admission(limit, used, in_flight, max_call_tokens) -> Admit | Exhausted | Contended
retry_after_seconds(now, resets_at) -> ceil((resets_at - now).total_seconds())
```

### 7.2 Request flow: `POST /v1/queries`
1. `require_user` guard: missing header → 401, malformed → 400, unknown → 404.
2. DTO validation: `hypothesis` 5–2000 chars after trimming, `title` ≤ 200 chars, `max_rows` within bounds → otherwise 422.
3. Insert a `query_requests` row with status `in_progress`.
4. `admit()` (§7.3). If denied: set the request to `rejected` and return **429 without calling the LLM**.
5. Run the generation harness (§8). Every LLM call is finalized with the actual tokens.
6. Update `query_requests` with the outcome, then return the response with `tokens_used` and `tokens_remaining`.

### 7.3 Admission with the in-flight claim
Each admission is one short transaction. The LLM call happens outside it.
1. `SELECT … FROM users WHERE user_id = :uid FOR NO KEY UPDATE` (D46): locks this user only, for milliseconds.
2. Mark this user's pending rows older than `PENDING_TTL_S` as `expired`.
3. Read `used` and `in_flight` with the hot query (§5).
4. `remaining ≤ 0` → **Exhausted**: 429 with `Retry-After = resets_at − now`.
5. `remaining − in_flight × MAX_CALL_TOKENS ≤ 0` → **Contended**: 429 with a short `Retry-After` (`CONTENDED_RETRY_S`).
6. Otherwise insert a `pending` row (attempt n), then commit, which releases the lock.

`finalize()` writes the actual tokens and sets `completed`, or `failed` with 0 tokens if the LLM returned no usage.

**Worked example**
```
used = 195,000 / 200,000, MAX_CALL_TOKENS = 15,000
A: remaining 5,000, in_flight 0 → admitted → LLM
B: remaining 5,000, in_flight 1 → 5,000 − 15,000 < 0 → 429 CONTENDED
A done: 3,500 → used 198,500
B retry: admitted → 3,500 → used 202,000 (overshoot ≤ one call, by design)
C: remaining ≤ 0 → 429 EXHAUSTED until 12:00Z
```

### 7.4 Edge cases and decided behaviour
| Case | Behaviour |
|---|---|
| Call admitted at 05:59:59, finishes at 06:00:04 | Charged to the 00:00 window (D11) |
| User created mid-window | Gets the full limit for the current window |
| `token_limit` changed mid-window (future admin API) | New limit applies from the next admission; past usage unchanged |
| `MAX_CALL_TOKENS` (static, D37) smaller than a real call | The call still completes and is billed in full; the overshoot is bounded by the call size. Measured in P3: real calls used 10.3K–12.3K, so it is set to 15,000 |
| LLM error, no usage reported | Call `failed`, 0 tokens; 502 returned |
| LLM timeout | Call `failed`, 0 tokens; 504. Documented risk: the provider may still bill |
| Self-correction needed but credits ran out partway | Stop retrying; return `status: "failed"`, `error_code: CREDITS_EXHAUSTED_MIDWAY`, with the tokens spent so far |
| Self-correction attempts used up | `status: "failed"`, last SQL + error returned |
| Query returns 0 rows, and every filter literal exists in the data | Valid result (`row_count: 0`), not an error |
| Query returns 0 rows because a filter literal doesn't exist in its column | Zero-row value check triggers self-correction with the closest real values (§8.2) |
| Result larger than `max_rows` | Truncated; `truncated: true`, `total_rows` gives the true count |
| Generated SQL outside the allowlist (DDL/DML, other tables, unknown functions, file/network access) | Rejected by the validator and fed back for correction; never executed. DuckDB's own lockdown blocks it even if the validator missed it (§8.3) |
| DuckDB query timeout | Interrupted; fed back for correction once ("simplify / aggregate"), then fail |
| Process crashes during an LLM call | Pending row expires after `PENDING_TTL_S`; credits are not locked forever |
| Duplicate `POST /v1/users` | 409 |
| Same `X-Request-Id` reused by a client | A new server `request_id` is generated; the client value is logged as `client_request_id` |
| Window length config doesn't divide 24h | App refuses to start (critical log) |

---

## 8. Generation Harness
One request flows through small, independently testable stages with typed inputs and outputs (`harness/stages.py`). `pipeline.py` wires them together and records a **trace**.

```
Hypothesis
  └─► [1] Build prompt   : versioned system prompt + cached schema card + title + hypothesis (+ prior SQL and error on retry)
  └─► [2] Generate       : LLM structured output (JSON schema) → GenerationDraft {interpretation, reasoning, assumptions[],
                           sql, output_kind (rows|aggregate)}
  └─► [3] Validate       : allowlist (§8.3): one SELECT/WITH, only `cloudtrail`, only its 19 columns,
                           only approved functions; LIMIT injected/capped
  └─► [4] Execute        : locked-down DuckDB cursor, in a thread, with timeout + row cap
  └─► [5] Value check    : if 0 rows, verify each filter literal exists in its column (§8.2)
  └─► [6] Explain        : deterministic result_summary + harness-computed confidence (§8.4); no extra LLM call
  └─► on failure at [3], [4] or [5]: back to [1] with the error, while attempts ≤ 1 + MAX_SELF_CORRECT
      and admission passes (every attempt is a billed LLM call, D12)
```

**Contracts**
- Each stage is a class with one async `run(input) -> output` method and no knowledge of HTTP or credits.
- The pipeline receives a `CreditGuard` callback (`admit` / `finalize`) for each LLM attempt, so credit logic stays in `CreditService` and is not tangled into the harness.
- **Trace:** for each attempt, the tokens, latency, outcome and error, plus timings per stage. It is returned in the API response and stored in the run folder.

**Why structured output (JSON schema):** the response is guaranteed to match the schema. No regex parsing of free text, and the explainability fields are always present.

### 8.1 Prompts as files (D27)
All prompt text lives in **separate files** under `prompts/<version>/`, never as strings in Python code:

| File | Content |
|---|---|
| `system.md` | Role, rules (read-only SQL, the table name, the output contract), null semantics and data quirks, plus the `{schema_card}` placeholder. Everything static sits here so it is prompt-cached |
| `user_template.md` | Template with placeholders: `{title}`, `{hypothesis}` |
| `retry_template.md` | Self-correction template: `{previous_sql}`, `{error}`, `{title}`, `{hypothesis}` |

- **`PromptRegistry`** (`llm/prompt_registry.py`) loads the version named by `PROMPT_VERSION` from `.env` once at startup. It checks that every file and placeholder is present (the app fails fast if one is missing) and computes a content hash.
- **Traceability:** the version and its hash are stored on every `query_requests` row and in each evaluation run's `run_config.json`, so every result can be tied to the exact prompt text that produced it.
- **Before/after:** v1 and v2 are side-by-side folders, so a diff between them shows exactly what changed. Switching versions is a one-line `.env` change.
- **Extensibility:** `PromptRegistry` is an interface. The file-based implementation is used now; a Langfuse-backed one can replace it later without changing the harness (§18).

### 8.2 Schema card and zero-row value check (D33)
**Schema card**, built once by `data-prep` and stored in the `_meta` table of `cloudtrail.duckdb`, so the data and its description can't drift apart:
- the 19 columns, all `VARCHAR`, with null rates and distinct counts
- **categorical** columns (≤ 200 distinct): the **full value list** with counts: `userIdentitytype`, `eventType`, `awsRegion`, `eventVersion`, `userIdentityarn`, `userIdentityprincipalId`, `userIdentityuserName`, `errorCode`, `eventSource`, `requestParametersinstanceType`
- **high-cardinality** columns: the **top 30 values** with counts: `eventName`, `userAgent`, `sourceIPAddress`, `userIdentityaccountId`, `userIdentityaccessKeyId`, `errorMessage`
- **identifiers** (`eventID`, `requestID`): 3 examples only
- **`eventTime`**: its range (`2017-02-12T19:57:06Z` → `2020-10-07T21:03:30Z`), not frequent values
- data conventions (empty = `NULL`, bracketed user agents, masked usernames, `CAST(eventTime AS TIMESTAMP)` for time filters) live in the prompt files (§8.1)
- **slim rendering in the prompt (D45):** value names without counts, 3 examples for opaque ID columns, `eventTime` as a range. About 5.6K Claude tokens; a real call measured 9.6K input tokens on the free model, down from 17.7K with the full card. The stored card keeps every value and count, so the zero-row value check still sees full lists

**Zero-row value check:** when a query runs but returns 0 rows, the harness extracts each literal compared against a column (`=`, `IN`, `LIKE`) and checks it exists in the data.
- If one doesn't, the attempt is treated as correctable: *"value 'UnauthorizedOperation' not found in errorCode; closest values: 'Client.UnauthorizedOperation', 'AccessDeniedException'"*.
- If every literal exists, 0 rows is accepted as a genuine answer.

### 8.3 SQL safety: two layers (D41)
**Layer 1, the allowlist validator (sqlglot).** Anything not explicitly allowed is rejected, with an LLM-friendly reason for self-correction:
- exactly one statement: `SELECT`, optionally with `WITH` (CTEs)
- the only table it may read is `cloudtrail`, plus CTE names it defines itself
- only the 19 known columns
- functions only from `allowlist.py`: aggregates, string, regex, date/time, `CAST`, `CASE`, `COALESCE` and window functions
- `LIMIT` injected or capped at `MAX_RESULT_ROWS + 1`, so truncation can be detected

**Layer 2, the locked-down DuckDB connection,** which holds even if layer 1 has a gap:
- opens `cloudtrail.duckdb` with `read_only=True`
- `SET enable_external_access = false`: no file or network access
- `SET lock_configuration = true`: queries can't change settings
- `threads` and `memory_limit` from config, plus a per-query timeout via `interrupt()`

### 8.4 Deterministic confidence (D34)
Confidence starts at 1.0, and the harness subtracts for objective risk signals. Each deduction is listed in `confidence_reasons`:

| Signal | Effect |
|---|---|
| Self-corrections needed | −0.15 each |
| 0 rows returned (values verified) | −0.20 |
| Each assumption the LLM declared | −0.05 (max −0.20) |
| Result truncated | −0.05 |
| `output_kind` contradicts the SQL (e.g. says aggregate but has no `GROUP BY`) | −0.15 |

The result is clamped to [0, 1]. The weights live in config and are documented, so the same inputs always give the same score. The LLM does **not** rate itself.

---

## 9. Evaluation Harness
**What it is:** an offline "exam" for the API. `python main.py` sends each known hypothesis (title + text) through `POST /v1/queries` over **real HTTP** and scores the returned rows **strictly** against `hypotheses_outcomes.json`. It doesn't change the model. **You** improve the prompt and validation from the results, run again, and compare.

**Iteration policy (D29):** improvements may only add rules that hold for **any** hypothesis (e.g. "frequency questions group by actor and action with a count"). No rule may target a specific hypothesis or the answer key. Where the answer key scopes a hypothesis more narrowly than its wording (e.g. #1 keeps only `No username found in supplied account`), the gap is explained in the report rather than fitted.

### 9.1 Modes
| Command | What it does | Spends credits |
|---|---|---|
| `python main.py` | **Live run**: creates a fresh user, runs all hypotheses **sequentially, one at a time**, scores them, and saves a new run folder | Yes |
| `python main.py --only 1,9a` | Live run on a subset (debugging) | Yes |
| `python main.py --replay runs/<folder>` | **Replay**: re-scores the saved responses of an earlier run with the current scoring code. No API or LLM calls | No |
| `python main.py --compare runs/<a> runs/<b>` | Prints and saves a before/after diff | No |

### 9.2 Live-run steps
1. Load the hypotheses and the answer key (`utils.py::load_hypotheses_outcomes`).
2. `POST /v1/users` → `eval-<timestamp>` (D21).
3. For each hypothesis, **in order**:
   1. `POST /v1/queries`.
   2. Save the raw response.
   3. Score it.
   4. Handle failures as in §9.6.
4. `GET /credits` and `GET /usage` for the user.
5. Write the run folder and copy `evaluation_results.json` to the repo root (a brief deliverable).

**Target:** always real HTTP to `API_BASE_URL` (D38). Before starting, `main.py` calls `/healthz`. If the API isn't reachable it stops at once: *"API not reachable at http://localhost:8000; run `make up` first."* `main.py` sends `include_results: true` and `max_rows = MAX_RESULT_ROWS`.

**Official runs (D40):** two, **before** (prompt v1, `MAX_SELF_CORRECT=0`, value check off) and **after** (prompt v2, all harness features on). v1 is an honest first attempt: the same schema card, a clear role and output contract, just without the lessons learned from failures.

### 9.3 Run folder (a new one per run, D19)
```
runs/2026-10-29T14-05-12Z_v1/
  run_config.json            # prompt_version, prompt_hash, model, llm_provider, effort, mode (live|replay), source run, settings, dataset file hash
  responses/<hypothesis_id>.json   # raw API response (SQL, explanation, rows, trace, usage)
  evaluation_results.json    # per-hypothesis + overall metrics + user credits/usage
  report.md                  # readable summary table
```

### 9.4 Scoring
**Normalise both sides** with the same function first:
- IDs stored as floats become canonical text (`811596193553.0` → `811596193553`)
- `NaN`/`NULL`/empty string all become one null value
- strings are trimmed
- column names are matched case-insensitively and alias-tolerantly (`user_agent` ↔ `userAgent`)
- a count column is recognised by name (`count`, `cnt`, `n`, `*_count`); failing that, the one remaining all-integer column is taken as the count (D47)

**Metrics per hypothesis**
| Metric | Meaning |
|---|---|
| `executed` | The query ran without error |
| `column_jaccard` | Overlap between expected and returned columns |
| `row_precision / recall / f1` | Row outputs: matched on `eventID` where both sides have it, otherwise on the tuple of shared columns; rows are matched as a multiset |
| `group_precision / recall / f1` | Aggregate outputs: matched on the group-key tuple, i.e. the expected non-count columns that the answer also returned. When the answer lacks some key columns, both sides are regrouped on the shared ones (counts summed); the missing columns already cost the columns check (D47) |
| `count_exact_rate`, `count_mean_rel_error` | Aggregate outputs: accuracy of the counts for matched groups |
| `tokens`, `latency_ms`, `attempts` | Cost and performance |

### 9.5 Composite score (D25)
Each hypothesis gets one score from 0 to 1, the weighted sum of four checks:

| Check | Plain question | Metric used | Weight |
|---|---|---|---|
| **Ran** | Did the SQL run without error? | `executed` (0 or 1) | 20% |
| **Right columns** | Did it return the expected columns? | `column_jaccard` | 20% |
| **Right rows / groups** | Did it find the right events, without misses or extras? | `row_f1` (row outputs) or `group_f1` (aggregate outputs) | 40% |
| **Right counts** | For "count by X" outputs, are the numbers correct? | `count_exact_rate` over matched groups | 20% |

**Rules**
- **The query fails to run or returns `status: "failed"`:** the score is 0. Nothing else is scored.
- **Row-shaped hypotheses (1, 2, 3, 6, 10) have no counts:** that check doesn't apply, and its weight is redistributed proportionally, giving ran 25%, columns 25%, rows 50%.
- **A hypothesis skipped for lack of credits:** reported as `skipped` and excluded from the averages. The report shows it explicitly.

**Worked examples**
| Hypothesis | Outcome | Ran | Columns | Rows/Groups (F1) | Counts | Score |
|---|---|---|---|---|---|---|
| #2 Root console logins (61 rows) | 58 returned, 55 correct, 6 missed; 15 of 19 columns | 1.0 | 0.79 | 0.92 | n/a | 0.25 + 0.20 + 0.46 = **0.91** |
| #7 Large EC2 (34 groups) | 30 of 34 groups found, no extras; 27 of 30 counts exact | 1.0 | 1.0 | 0.94 | 0.90 | 0.20 + 0.20 + 0.375 + 0.18 = **0.96** |
| Any | SQL fails to run | 0 | — | — | — | **0** |

**Why these weights:** finding the right events matters most to a threat hunter (40%). Running and the right columns give partial credit for a correct method, which makes improvement between prompt versions visible (20% each). Counts matter for the frequency-based hypotheses such as brute force and reconnaissance (20%).

**Overall score:** the macro average of the per-hypothesis scores, so every hypothesis counts equally regardless of its size. The report also shows **each check separately**, per hypothesis and on average, so one total never hides where a query went wrong. The before/after diff compares the overall score and each check.

Only this **strict** score is computed (D30). Relaxed scoring is future scope (§18).

### 9.6 Failure handling during a run (D42)
| Situation | Behaviour |
|---|---|
| `status: "failed"` (SQL couldn't be fixed) | Score 0; continue |
| 429 `CREDITS_EXHAUSTED` | Stop calling; mark the remaining hypotheses `skipped` (excluded from averages, listed in the report) |
| 429 `CREDITS_CONTENDED` | Wait `Retry-After` once, then retry |
| 502 / 504 | Retry that hypothesis once after a short wait; if it fails again, record `error`, score 0, continue |
| API unreachable mid-run, or Ctrl-C | Stop; the run folder keeps everything done so far, marked `incomplete` in `run_config.json` |

### 9.7 Expected vs found (D35)
For each hypothesis the report explains how the results map to the expected findings, deterministically from the strict comparison:
- expected count, returned count, and the **matched / missing / extra** counts
- up to **3 example rows** each of missing and extra
- a one-line note from the engineer where the gap comes from answer-key scoping rather than a query error (D29)

Together with the API's `result_summary` (what was found), this covers the brief's "how results map to expected findings".

---

## 10. Performance
| Area | Technique |
|---|---|
| Dataset | One-time CSV → native DuckDB file (`cloudtrail.duckdb`, columnar, compressed) by the `data-prep` service; skipped when the CSV hash is unchanged. Queries read only the columns they need |
| DuckDB | One read-only, locked-down connection opened at startup; a **cursor per query** in `asyncio.to_thread`; `threads`, `memory_limit` from config; timeout via `interrupt()` |
| Schema card | Built once by `data-prep` (columns, null rates, value lists) and cached, keyed by the dataset hash; loaded at API startup. The zero-row value check uses the same cached value sets (no extra query for low-cardinality columns) |
| LLM | Anthropic **prompt caching** on the static system prompt and schema card → lower latency; `max_tokens` capped; SDK retries with backoff |
| Credits DB | asyncpg connection pool (size from config), per-user row lock held for ms only, covering index → index-only scan for the hot query, prepared statements |
| HTTP | Fully async request path; gzip for large result sets; results capped by `max_rows` |
| Startup | Fail fast on invalid config, missing dataset or a non-dividing window length |

---

## 11. Logging, Errors & Config
- **Logging:** structlog JSON with `request_id` and `user_id` bound through contextvars. One log point per failure:
  | Failure point | Level |
  |---|---|
  | Guard reject (401/400/403/404) | warning |
  | Validation reject (422) | info |
  | Credit deny (exhausted / contended) | info |
  | LLM error / timeout (status, attempt) | error |
  | SQL rejected by the validator (rule) | warning |
  | DuckDB error / timeout | error |
  | DB error | error |
  | Startup config invalid | critical |

  API keys are never logged; hypothesis text is truncated to 200 chars.
- **Errors:** an `AppError` hierarchy (`AuthError`, `NotFoundError`, `ForbiddenError`, `ConflictError`, `CreditsExhausted`, `CreditsContended`, `UpstreamError`, `TimeoutError`) maps to the envelope in §6. Unhandled exceptions → 500, with no stack trace in the response.
- **Guards:** `require_user` and `require_self` are reusable FastAPI dependencies.
- **Config:** `.env` is the **single source of configuration** for docker-compose, the API, the tests and `main.py`. Nothing is hard-coded. `Settings` (pydantic-settings) validates it at startup and builds the DB URLs from the `POSTGRES_*` parts unless `DATABASE_URL` is set. `.env.example` is committed with safe defaults; `.env` is gitignored.
  ```
  ANTHROPIC_API_KEY=
  LLM_MODEL=claude-sonnet-5-5
  LLM_PROVIDER=anthropic          # anthropic | openrouter | claude_code (local CLI on your subscription, dev only) (D44)
  OPENROUTER_API_KEY=             # when LLM_PROVIDER=openrouter
  OPENROUTER_MODEL=anthropic/claude-sonnet-5.5
  LLM_EFFORT=medium               # sampling params (temperature) are not supported by the model
  LLM_MAX_TOKENS=8000             # includes thinking tokens
  LLM_TIMEOUT_S=90
  CLAUDE_CLI_PATH=claude
  CLAUDE_CLI_MAX_CONCURRENCY=2
  PROMPT_VERSION=v2
  COMPOSE_PROJECT_NAME=threat-hunt
  POSTGRES_USER=threat_hunt
  POSTGRES_PASSWORD=change-me
  POSTGRES_DB=threat_hunt
  POSTGRES_TEST_DB=threat_hunt_test
  POSTGRES_HOST=localhost          # compose sets "db" for the api container
  POSTGRES_PORT=5433               # host port; change if 5433 is taken
  DATABASE_URL=                    # optional override (bring your own Postgres); otherwise built from POSTGRES_*
  DB_POOL_SIZE=10
  TOKEN_LIMIT_DEFAULT=200000
  MAX_TOKEN_LIMIT=10000000
  WINDOW_HOURS=6
  MAX_CALL_TOKENS=15000           # measured in P3: largest real call 12.3K + headroom (D37)
  PENDING_TTL_S=120
  CONTENDED_RETRY_S=5
  DATASET_CSV_PATH=./data/nineteenFeaturesDf.csv
  DUCKDB_PATH=./data/cloudtrail.duckdb
  QUERY_TIMEOUT_S=20
  MAX_RESULT_ROWS=10000
  MAX_SELF_CORRECT=2               # 0 for the 'before' run
  ZERO_ROW_VALUE_CHECK=true        # false for the 'before' run
  SCHEMA_CARD_MAX_DISTINCT=200     # full value list at or below this cardinality
  SCHEMA_CARD_TOP_N=30
  CONFIDENCE_PENALTY_RETRY=0.15
  CONFIDENCE_PENALTY_ZERO_ROWS=0.20
  CONFIDENCE_PENALTY_ASSUMPTION=0.05
  CONFIDENCE_PENALTY_ASSUMPTION_MAX=0.20
  CONFIDENCE_PENALTY_TRUNCATED=0.05
  CONFIDENCE_PENALTY_SHAPE_MISMATCH=0.15
  DUCKDB_THREADS=4
  DUCKDB_MEMORY_LIMIT=2GB
  API_BASE_URL=http://localhost:8000   # main.py always calls the API over HTTP
  LOG_LEVEL=INFO
  ```

---

## 12. Testing
Tests use pytest + pytest-asyncio, a `FakeGateway` (scripted responses with token usage, and a call counter), a `FakeClock`, the **`threat_hunt_test` Postgres database** (tables truncated between tests) and a small DuckDB fixture. Tests drive the API in-process with httpx (test plumbing only; `main.py` always uses real HTTP). They need the project's Docker DB running (`make db-up`); the test DB URL comes from `POSTGRES_TEST_DB` in `.env`.

**Required by the brief**
- [ ] A request within the limit succeeds and its usage is recorded
- [ ] A request after credits run out → 429, and the LLM is **not** called (FakeGateway call count = 0)
- [ ] Credits restored when a new window starts (FakeClock moved past the boundary)
- [ ] Concurrent requests near the limit don't overspend (`asyncio.gather`; total ≤ limit + one call)
- [ ] Usage persists across an API restart (dispose engine → new app on the same database → same usage)

**Business logic (pure unit tests)**
- [ ] `window_bounds` at 05:59:59, 06:00:00, 23:59:59 and a day rollover
- [ ] `decide_admission` across exhausted / contended / admitted cases
- [ ] Pending claim expires after the TTL

**API and harness**
- [ ] Guards: 401 / 400 / 403 / 404 / 422; 409 for a duplicate user
- [ ] Response shapes match the DTOs; `X-Request-Id` echoed; 429 has `Retry-After`
- [ ] Validator allowlist: rejects DDL/DML, other tables, unknown columns and functions, multiple statements; allows CTEs and window functions; injects or caps LIMIT
- [ ] Locked-down DuckDB: `read_csv`, `COPY`, `ATTACH` and `SET` fail even when called directly (validator bypassed)
- [ ] Zero-row value check: a missing literal triggers a retry with the closest values; existing literals with 0 rows are accepted
- [ ] Confidence: the same inputs give the same score; each deduction appears in `confidence_reasons`
- [ ] `include_results=false` returns no rows but the same SQL, summary and usage
- [ ] Self-correction: an invalid first draft → a second attempt succeeds; two `token_usage` rows
- [ ] Retries stop when credits run out midway
- [ ] Executor timeout and row cap
- [ ] Evaluator normalisers and metrics on small fixtures; replay reproduces the same scores
- [ ] `main.py` failure handling (§9.6) with a stubbed API: skipped, retried once, incomplete

**Live (opt-in, D43):** `pytest -m live` sends one real hypothesis through the configured real gateway (`anthropic` or `claude_code`). It checks that the structured output parses, that `response.usage` (including cache fields) is recorded in `token_usage`, and that the SQL runs. It's skipped automatically when `ANTHROPIC_API_KEY` is unset and costs about 10K tokens.

---

## 13. Build Phases
| Phase | Scope | Exit criteria |
|---|---|---|
| P0 | Scaffold: config, logging, errors, middleware, guards, `.env.example`, Makefile, **docker-compose with Postgres** | `make db-up` healthy; app boots; `/healthz` OK; startup fails on bad config |
| P1 | `schema.sql`, users + credits modules, policy functions | All credit/guard tests green with FakeGateway |
| P2 | `data-prep` service (CSV → `cloudtrail.duckdb`), schema card, allowlist validator, locked-down executor, zero-row value check | Validator, lockdown and executor tests green |
| P3 | Generation harness + LLM gateway + confidence scorer + `POST /v1/queries` + `query_requests`; **measure the real worst-case call and set `MAX_CALL_TOKENS`** | A real hypothesis returns SQL, explanation, trace and usage; live test green |
| P4 | Evaluation harness (live over HTTP, replay, compare, expected-vs-found) → **'before' run** | `runs/<ts>_v1/` with metrics |
| P5 | Failure analysis → generic prompt rules (v2) + harness features on → **'after' run** | Before/after diff |
| P6 | Docs: README (setup, Mermaid diagrams for architecture and the rate-limit flow, extending to other datasets), this file, `EVALUATION_REPORT.md` | Submission checklist complete |

---

## 14. Prompting Strategy
Prompt files live in `prompts/<version>/` (§8.1); Python never contains prompt text.

| File | Content |
|---|---|
| `system.md` | Role (threat-hunting analyst writing DuckDB SQL), SQL rules (one SELECT, only `cloudtrail`, text columns, exact values, `CAST(eventTime AS TIMESTAMP)`), v2's shape and scope rules (§15), the output fields, then `{schema_card}` |
| `user_template.md` | `{title}` + `{hypothesis}` only; no hypothesis id, so nothing can key off the answer key (D32) |
| `retry_template.md` | The hypothesis again, the previous SQL and the problem, with "keep what was right; fix only what the problem requires" |

- **One cached system prompt.** The schema card sits inside `system.md`, so the system prompt is identical for every call and every user and is sent with a cache marker (Anthropic `cache_control`; the same on OpenRouter). Only the short user or retry message changes.
- **Schema card (D33, D45):** per column, its full value list when it has ≤ 200 distinct values (e.g. all 103 `errorCode` values), the most frequent 30 otherwise, 3 examples for opaque IDs, and the `eventTime` range. Values are listed without counts. This is what lets the model write `Client.UnauthorizedOperation` rather than the hypothesis' `UnauthorizedOperation`, at about 9.6K input tokens per call.
- **Structured output, not free text (D6):** every call carries a strict JSON schema (`interpretation`, `reasoning`, `assumptions`, `sql`, `output_kind`), enforced by the provider's structured-output mode and validated again with Pydantic. Malformed output is a correctable failure.
- **Deterministic feedback:** retry messages come from the validator (e.g. "Unknown table `events`"), DuckDB's error, the timeout, or the value check ("value 'command/%' not found in userAgent; closest values: …"), never from another LLM call.
- **No few-shot examples.** Examples drawn from the 11 hypotheses would leak the answer key, and invented ones would steer the shape of every answer. v2 uses short generic rules instead, each traced to a failure pattern (§15).
- **Sampling:** `effort: medium`; temperature is not set (Sonnet 5.5 rejects it, D6).
- **Confidence is not prompted.** The harness computes it from objective signals (§8.4).
- **Versioning:** the registry checks every placeholder at startup and hashes the files (12 hex chars). The hash appears in every response, every `query_requests` row and every run folder, so a score always maps to exact prompt text.

## 15. Iteration Log
All runs use the same model (`nvidia/nemotron-3.5-super-vl:free` via OpenRouter, D44), the same dataset hash and a fresh user with the brief's 200K limit. Scores are the strict composite (§9.5), re-scored with the final scoring code (D49).

| Run folder | Prompt (hash) | Harness | Composite | Ran · Columns · Rows/Groups · Counts | Tokens (calls) |
|---|---|---|---|---|---|
| `runs/2026-10-29T19-19-34Z_v1` | v1 (`9cd12dc42e98`) | no self-correction, no value check | **0.501** | 1.00 · 0.26 · 0.49 · 0.00 | 121,673 (11) |
| `runs/2026-10-29T19-33-48Z_v2` | v2 iteration 1 (`1761c0325962`) | self-correction 2, value check on | 0.715 | 1.00 · 0.49 · 0.75 · 0.36 | 135,114 (12) |
| `runs/2026-10-29T19-39-48Z_v2` | **v2 final** (`a63b974ab7b1`) | self-correction 2, value check on | **0.794** | 1.00 · 0.58 · 0.82 · 0.67 | 139,770 (12) |

Iteration 1's raw responses are not kept (only its scores and report), to keep the repository small; the two official runs keep everything and replay exactly.

**Failure analysis of v1 → rules added in v2.** Every rule is generic (D29): it names no hypothesis and no answer-key value (checked by grep against all hypothesis-specific terms).

| v1 failure (hypotheses) | Rule added in v2 | Why it is generic |
|---|---|---|
| "Who / how often / with what" hypotheses came back as raw events, so no counts, and truncated at 10K rows (4, 5, 7, 8, 9a, 9b) | **Choose the output shape:** events for one specific rare action; grouped counts for who/how-often/with-what questions or a property many events share | The same question decides the shape for any hypothesis; a raw list of thousands of events is unusable for any analyst |
| Grouped answers carried extra metrics (first/last seen, distinct counts, lists) and extra group columns (1, 4, 8) | Group by the actor + the attributes the hypothesis names (+ IP and user agent only for how/where an actor connects); select only those plus `COUNT(*) AS count` | A fixed aggregate shape is easier to read and compare |
| Row answers returned an arbitrary subset of columns (2, 3, 6, 10) | Events are returned complete (`SELECT *`) | An analyst pivots on any field of a matching event |
| Filters broadened to related actions such as create/describe/list (3, 6) | Match only the actions that perform the behaviour; leave out read/list/describe unless asked (neutral example: security-group tampering) | Holds for any action-based hypothesis |
| Extra values beyond those the hypothesis named (4) | Use exactly the named values; if one is not in the data as written, use the listed value that contains it | Holds for any hypothesis that names values |
| Invented thresholds and caps (`HAVING COUNT(*) >= 5`, `LIMIT 100`) (1, 8) | No thresholds, LIMITs or time windows the hypothesis does not state | Unstated cut-offs silently drop findings |
| 0 rows: failures filtered on `errorCode`, but failed console sign-ins only set `errorMessage` (1) | A failed call has `errorCode` or `errorMessage` set; console sign-in failures carry only `errorMessage` | A fact about the dataset, true for any hypothesis about failures |

**Iteration 1 → final:** iteration 1 still returned events for hypotheses selected by a shared property (instance size, user-agent pattern) and added unrequested group columns, so the shape rule was sharpened ("a property that many events share", "add no other group columns"). Rules tried and dropped: translating a quoted `*` into an anchored `LIKE` pattern (it returns 0 rows on this data and helps no hypothesis).

**Why iteration stopped here.** The remaining gaps are either answer-key scoping (1, 4, 8, 9b; explained per hypothesis in `report.md` from `evaluation/notes.json`, D35) or the model's shape choice for #7 (events, then truncated at 10K rows). Further prompt rules aimed at those would be fitting the answer key (D29). A generic harness fix for #7 is listed in §18.

## 16. Challenges & Solutions
- An initial dataset copy (`dec12_18features.csv`) was coarsened and could not match the answer key. Spotted by comparing rows by index; switched to `nineteenFeaturesDf.csv` (§2, D7).
- The answer key mixes raw rows and aggregates with varied column sets. A shape-aware scorer handles both (§9.4).
- Hypothesis wording doesn't always match real values (`UnauthorizedOperation` vs `Client.UnauthorizedOperation`). Handled by the schema card's value lists and the zero-row value check (§8.2).
- `enable_external_access=false` would block reading Parquet files at query time, so the data is stored as a native DuckDB file instead (§8.3).
- The CSV has 1,939,214 lines but 1,939,207 records: 7 quoted fields contain line breaks. DuckDB and Python's `csv` module agree record for record, and the answer-key indices line up with `rowid`.
- **Tokens per call.** The first full schema card made one call 19.3K tokens, so a 200K window held only ~10 calls. Slimming the card (values without counts, examples for IDs) brought input to 9.6K and calls to 10–12K, measured on real calls; `MAX_CALL_TOKENS` was then set to 15,000 from those measurements (D37, D45).
- **Model API changes.** Sonnet 5.5 rejects `temperature` and forced `tool_choice`, so generation uses structured outputs with `effort` (D6).
- **No API key, only a subscription.** The gateway became an interface with three providers: Anthropic, OpenRouter and the local Claude Code CLI. The official runs used a free OpenRouter model because the available key had a $0 limit (D44).
- **asyncpg and a comment-only `schema.sql`.** Running a script with no statements crashed asyncpg; startup now skips an empty schema file.
- **Locks and foreign keys.** `FOR UPDATE` on the user row would also block the FK checks of concurrent audit inserts; `FOR NO KEY UPDATE` serialises admissions without that (D46).
- **A scorer bug found by its own output.** The "single integer column is the count" fallback read `userIdentityaccountId` (all digits) as a count on raw-event answers. Fixed so dataset columns never qualify, and all runs re-scored from their saved responses (D49).
- **Shape is the model's hardest choice.** The same wording ("brute force", "launch") reads as events to one prompt and as counts to another, and the free model flips between runs. Two prompt iterations fixed most cases; the rest are explained rather than fitted (D50).

## 17. Limitations
- `X-User-Id` is identification only; production would need real authentication.
- The in-flight claim allows up to one call of overshoot by design (D4).
- The design targets a single API instance. Postgres row locks already make admission safe across instances, but DuckDB and the dataset are local to each instance (see §18).
- Hypothesis wording is sometimes ambiguous (e.g. #1 "failed console login"; the answer key keeps only `No username found in supplied account`). A reasonable broader query shows up as lower precision.
- A timed-out LLM call is recorded as 0 tokens even though the provider may have billed it.
- `MAX_CALL_TOKENS` is static; if prompts grow past it, concurrent calls near the limit can overshoot by more than planned until it's updated.
- Strict scoring penalises queries that are logically right but scoped or grouped differently from the answer key; the report explains these cases, but the score doesn't credit them.
- With 2 official runs, the before/after gain can't be attributed to individual changes (prompt vs self-correction vs value check). In the after run only one hypothesis needed a correction, so most of the gain is the prompt.
- One run per configuration on a free model (D44): run-to-run variation of a few hundredths per hypothesis is expected, and the default production model (Sonnet 5.5) was not measured.
- The v2 rules were derived from failures on the same 11 hypotheses they are scored on. They are generic by construction and checked for hypothesis-specific terms, but there is no held-out set.
- Deterministic confidence reflects execution risk, not semantic correctness. A clean query can still answer the wrong question.

## 18. Future Scope
- **Parallel evaluation** with a bounded concurrency limit (currently sequential, D18).
- **Multi-instance deployment:** several API replicas behind a load balancer. Credit admission is already safe; the log data would move to a shared store (e.g. Parquet on S3 behind a hardened engine).
- **Reserve-then-settle** credits for zero overshoot.
- **Alembic migrations** once the schema starts changing.
- **Langfuse for prompt management and LLM observability:**
  - **Prompt versioning:** prompts move from `prompts/<version>/` files into Langfuse prompt management, with versions, labels such as `production`/`staging`, and rollbacks without a deploy. A `LangfusePromptRegistry` implements the same `PromptRegistry` interface (§8.1), so the harness doesn't change.
  - **Token usage and cost monitoring:** every LLM call is traced as a Langfuse generation (prompt version, tokens, latency, cost, errors). This gives per-user and per-prompt dashboards beyond what `/usage` shows. It is added as an observer hook in `LLMGateway`.
  - **Evaluation tracking:** evaluation runs are pushed as Langfuse datasets and scores, so prompt versions can be compared in its UI.
  - **Postgres stays the source of truth for credits.** Langfuse is for observability only and is never used to enforce limits.
- **Automated prompt improvement** from evaluation failures.
- **Truncation feedback:** when a row-shaped result exceeds `MAX_RESULT_ROWS`, feed that back as a correction ("summarise with grouped counts") instead of returning a truncated list. It is generic and would fix #7's remaining gap; left out of P5 so the before/after compares prompt changes only.
- **Relaxed scoring + diagnosis labels:** a second score that ignores extra columns and rolls finer or coarser groupings up to the answer key's keys, with automatic labels (`broader_filter`, `narrower_filter`, `different_grouping`, `wrong`).
- **Ablation with repeated runs:** five configurations (A v1 bare · B v1 + self-correction · C v1 + self-correction +
  value check · D v2 bare · E v2 full), 3 runs each with a fresh user, aggregated to mean and min/max per check and per
  hypothesis. A→B, B→C, A→D and D→E each isolate one change; the repeats show run-to-run variance (the model is called
  without a fixed temperature). A script starts one server per configuration on a spare port and refuses to run if
  `/healthz` doesn't report the expected settings. Roughly 13 new runs, 2–2.5 hours on the free model.
- **Held-out hypotheses:** 3–4 new ones the v2 rules were never tuned on, e.g. IAM privilege escalation
  (`AttachUserPolicy`/`AttachRolePolicy`/`PutUserPolicy`/`CreatePolicyVersion`), snapshot sharing
  (`ModifySnapshotAttribute`), security groups opened to the internet (`AuthorizeSecurityGroupIngress`), and EC2
  credential harvesting (`GetPasswordData`/`CreateKeyPair`/`ImportKeyPair`, grouped counts). All exist in the data. The
  answer key would be generated from reference SQL, committed and frozen before any run, and scored separately from the
  official 11, so a before/after gap on it shows whether the rules generalise.
- **LLM-blended confidence + calibration check:** combine the harness signals with the LLM's self-rating, and check in the report that high-confidence queries actually score higher.
- **Agentic value lookup:** a `lookup_values(column, pattern)` tool the LLM can call before writing SQL, for long-tail values.
- **`main.py --resume runs/<folder>`:** continue an incomplete run with the same user.
- **Measured `MAX_CALL_TOKENS`:** computed at startup with Anthropic's token-counting endpoint instead of a static value.
- **Model A/B** comparison (Sonnet vs Haiku/Opus) and latency benchmarks.
- **Streamlit demo UI.**
- **Admin API** for changing user limits.
