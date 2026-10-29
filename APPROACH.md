# APPROACH: Threat-Hunting Query Generator with Per-User Credits

## At a glance

**The problem.** An analyst writes a hypothesis in plain English: *"Attackers call GetCallerIdentity to learn which
account they're in."* The system turns it into SQL over **1.9M AWS CloudTrail events**, runs it, explains it, and
charges every LLM call to the user's budget of **200K tokens per 6-hour UTC window**.

**The result.** Every answer is scored strictly against the provided answer key. The scoring is in §9.5.

| Check | Before (prompt v1) | After (prompt v2 + harness) |
|---|---|---|
| **Overall score** | 0.50 | **0.79** |
| Found the right events or groups | 0.49 | **0.82** |
| Got the counts right | 0.00 | **0.67** |
| Returned the expected columns | 0.26 | **0.58** |
| Query ran | 11 / 11 | 11 / 11 |

5 of the 11 hypotheses now score 0.93 or more, including two perfect 1.00s. Most of the remaining gap comes from the
answer key scoping hypotheses more narrowly than their wording. Those cases are explained in the report, not fitted
(§15).

**Five ideas behind the design**
1. **Credits can't be overspent, even under concurrency.**
   - Each LLM call is admitted in one short transaction that locks only that user's row and records an in-flight claim.
   - Two parallel calls can't both spend the last credits; the most a user can go over is one call.
   - When nothing is left, the API returns 429 with `Retry-After` set to the window reset, and the LLM is never called.
   - (§5, §7)
2. **The model sees real values, not just column names.**
   - A schema card lists the actual values, such as all 103 error codes. The model then writes
     `Client.UnauthorizedOperation`, the value in the data, not `UnauthorizedOperation`, the word in the hypothesis.
   - If a query finds 0 rows because a value doesn't exist, the harness sends the closest real values back to the
     model and it retries (§8.2).
3. **Untrusted SQL is contained twice.** A sqlglot allowlist rejects anything that isn't a single read of the one
   table. The DuckDB connection itself is read-only, with no file or network access, so it holds even if the
   validator misses something (§8.3).
4. **Every answer explains itself.** It comes with:
   - the model's interpretation of the hypothesis, its reasoning and its assumptions, guaranteed by structured output
   - a confidence score that the harness computes from objective signals, with a reason for each deduction (§8.4)
5. **The evaluation is hard to game.**
   - `main.py` calls the API over real HTTP, like any client.
   - The answer key is never shown to the model, and prompt rules may not name a hypothesis.
   - Every score is tied to the exact prompt text through a hash, and `--replay` reproduces it (§9, §15).

**One request, end to end**
```
POST /v1/queries ─► guards ─► admit credits ──(none left)──► 429 + Retry-After, LLM not called
                                   │
                                   ▼
                    LLM writes SQL + explanation ─► validate ─► run on DuckDB ─► 0 rows? check values
                                   ▲                                               │
                                   └──── invalid SQL / error / missing value ◄─────┘   each retry is admitted and billed
                                   │
                                   ▼
            record actual tokens ─► response: SQL · explanation · confidence · rows · trace · credits left
```

**Stack:**
- **Service:** FastAPI, async, built as a modular monolith.
- **Postgres 16:** the credits and the audit trail.
- **DuckDB:** the log data, embedded.
- **LLM:** Claude Sonnet 5.5 by default. The official runs used a free OpenRouter model (D44).
- **Runs** in Docker Compose, with 69 tests.

**What's next** (§18):
- **Truncation feedback**, to fix the one real query weakness left (#7).
- **Relaxed scoring.**
- **An ablation with repeated runs.**
- **A held-out set** of new hypotheses.

**Reading guide:**
- **10 minutes:** this page, §7.3 (admission), §15 (how the prompt improved).
- **Design depth:** §5–§9.
- **Every decision with its alternatives:** [`DECISIONS.md`](DECISIONS.md). References such as **D4** point there.

---

## Contents
1. [Context](#1-context) · 2. [Data Findings](#2-data-findings) · 3. [Key Decisions](#3-key-decisions) ·
4. [Architecture](#4-architecture) · 5. [DB Schema](#5-db-schema) · 6. [API Contracts](#6-api-contracts) ·
7. [Business Logic](#7-business-logic--edge-cases) · 8. [Generation Harness](#8-generation-harness) ·
9. [Evaluation Harness](#9-evaluation-harness) · 10. [Performance](#10-performance) ·
11. [Logging, Errors & Config](#11-logging-errors--config) · 12. [Testing](#12-testing) · 13. [Build Phases](#13-build-phases) ·
14. [Prompting Strategy](#14-prompting-strategy) · 15. [Iteration Log](#15-iteration-log) ·
16. [Challenges](#16-challenges--solutions) · 17. [Limitations](#17-limitations) · 18. [Future Scope](#18-future-scope)

---

## 1. Context
The brief gives the system three jobs:
- **Generate:** hypothesis → explained DuckDB SQL.
- **Evaluate:** score against `hypotheses_outcomes.json` and show before/after results.
- **Meter credits:** keep a per-user token budget in a database, behind an API.

It puts the most weight on the harness, the DB schema, the APIs and the business logic, so this document goes deepest
there (§5–§9). Multi-instance deployment and parallel evaluation are out of scope (§18).

## 2. Data Findings
- **Dataset:** `nineteenFeaturesDf.csv`, as the brief requires (D7). It has 1,939,207 records in 19 columns; 7
  records contain line breaks inside quoted fields. An earlier copy, `dec12_18features.csv`, was coarsened
  (month-only times, cut IPs) and couldn't match the answer key, so it was dropped.
- **It lines up with the answer key exactly.** The key's index values are row positions in the CSV. 118 expected rows
  were checked cell by cell against the built database, with 0 mismatches.

| Quirk | Example | Handling |
|---|---|---|
| IDs stored as floats | `811596193553.0` | Normalised to text on both sides before comparing |
| Hypothesis wording ≠ real value | `UnauthorizedOperation` vs `Client.UnauthorizedOperation` (351,760 rows) | Value lists in the schema card + zero-row value check (§8.2) |
| Failed console sign-ins have no `errorCode` | only `errorMessage` is set | Stated in prompt v2 (§15) |
| Timestamps are text | `2017-05-17T23:23:34Z` | Kept exactly as in the CSV (D36); the prompt says to use `CAST(eventTime AS TIMESTAMP)` |
| Bracketed or masked values | `[S3Console/0.4]`, `HIDDEN_DUE_TO_SECURITY_REASONS` | Kept as-is; visible in the schema card |

## 3. Key Decisions
| Area | Choice | Why |
|---|---|---|
| Service | FastAPI, async, modular monolith (D1, D5) | Clear module boundaries without running microservices |
| Credit store | Postgres 16, SQLAlchemy 2 async on asyncpg, hand-written `schema.sql` (D2, D15, D16) | Row locks make admission safe under concurrency; usage survives restarts |
| Overspend | An in-flight claim at admission; let a running call finish, block the next one (D4) | Overshoot is bounded to one call, with no complex reservation |
| Windows | Fixed UTC blocks; a call counts in the window it was admitted in (D10, D11) | Exact 00/06/12/18 boundaries, no split accounting |
| Retries | Every self-correction attempt is admitted and billed (D12) | Every LLM call spends credits, as the brief requires |
| Log engine | Embedded DuckDB file built once by a `data-prep` job (D3, D36, D39) | Fast columnar scans; `SELECT *` matches the source data |
| SQL safety | Allowlist validator + locked-down DuckDB (D41) | Defence in depth around SQL written by an LLM |
| Query quality | Schema card with real values + zero-row value check (D33) | Catches value traps without extra LLM calls |
| Confidence | Computed by the harness from objective signals (D34) | Explainable and repeatable; LLM self-ratings are poorly calibrated |
| LLM | Structured output; prompts as versioned files; Anthropic, OpenRouter or Claude Code CLI behind one interface (D6, D27, D44) | Explanation fields always present; prompts diffable; runs with any of the three |
| Evaluation | Strict scoring; real HTTP; a fresh user per run; replayable run folders (D18–D21, D30, D38, D40) | An honest, reproducible before/after |
| Integrity | Answer key never shown to the LLM; only generic prompt rules (D8, D29) | No overfitting to the 11 hypotheses |

## 4. Architecture
```
Client ─► Middleware (request id, timing, access log, gzip)
       ─► Guards (X-User-Id → 401/400/404/403; DTO validation → 422)   ← early exits
       ─► Controllers (HTTP only)  ─► Services (business logic, no HTTP)
            ├─ UserService
            ├─ CreditService  ── admit() / finalize() ── CreditRepository ─► Postgres
            └─ QueryService   ── GenerationHarness (§8) ── QueryRepository ─► Postgres
                                   ├ LLMGateway (Anthropic | OpenRouter | Claude Code | Fake)
                                   ├ SqlValidator (sqlglot allowlist)
                                   └ DuckDBExecutor (read-only, timeout, in a thread)
main.py ─► EvaluationHarness (§9) ─► the API over HTTP
```
**Layering rules:**
- Controllers never touch the DB, services never touch HTTP, and repositories hold all SQL.
- DTOs are separate from ORM models.
- Modules call each other's services, never each other's repositories.
- The LLM, DuckDB and the clock sit behind small `Protocol`s, so tests swap in fakes.
- Rules that need no I/O are pure functions (`credits/policy.py`).

The folder layout and the Docker setup are in the [README](README.md).

## 5. DB Schema
The full DDL is in [`schema.sql`](schema.sql), applied at startup. Postgres 16; every timestamp is `TIMESTAMPTZ` in UTC.

| Table | One row per | Key columns |
|---|---|---|
| `users` | user | `user_id` (checked format), `token_limit > 0` |
| `query_requests` | API request (the business unit, audit trail) | status `in_progress → succeeded / failed / rejected`, `error_code`, final SQL, confidence, attempts, prompt version + hash, latency |
| `token_usage` | LLM call (the billing unit) | `request_id`, `attempt`, `input_tokens`, `output_tokens`, `window_start`, status `pending / completed / failed / expired`; `UNIQUE(request_id, attempt)` |

**Design notes**
- **`window_start` is stored on every call,** so "tokens used this window" is a plain indexed lookup, with no date
  math in the query:
  ```sql
  SELECT COALESCE(SUM(input_tokens + output_tokens), 0) AS used,
         COUNT(*) FILTER (WHERE status = 'pending')     AS in_flight
  FROM token_usage WHERE user_id = :uid AND window_start = :ws;
  ```
- **A covering index** `(user_id, window_start) INCLUDE (input_tokens, output_tokens, status)` answers that query from
  the index alone.
- **Locking:** admission locks only that user's row with `FOR NO KEY UPDATE` (D46). Different users never block each
  other, and foreign-key checks from concurrent inserts aren't blocked either.
- **CHECK constraints** reject negative tokens, bad IDs and unknown statuses at the DB level, behind the DTO validation.

## 6. API Contracts
**Every response:** JSON, with `X-Request-Id` echoed back.

**Every error:** one envelope, `{"error": {"code", "message", "details"}, "request_id"}`.

| Method & path | Purpose |
|---|---|
| `POST /v1/users` | Create a user (`user_id` and `token_limit` optional). No `X-User-Id` needed (D23) |
| `POST /v1/queries` | Hypothesis → SQL, explanation, confidence, rows, trace, usage |
| `GET /v1/users/{id}/credits` | Used, remaining and in-flight tokens; window start; reset time |
| `GET /v1/users/{id}/usage` | Every LLM call in the current window, with totals |
| `GET /healthz` | DB and DuckDB status, plus the harness configuration (prompt hash, settings) |

**`POST /v1/queries`** takes a `hypothesis` (5–2000 characters), and optionally a `title`, `include_results` and
`max_rows`. There is no hypothesis id, so nothing can key off the answer key (D32). Response, shortened:
```json
{
  "status": "succeeded",
  "query": { "sql": "SELECT * FROM cloudtrail WHERE userIdentitytype = 'Root' AND …", "dialect": "duckdb" },
  "explanation": {
    "interpretation": "Find console sign-ins made with the root account…",
    "reasoning": "Root is identified by userIdentitytype = 'Root'; console sign-ins are…",
    "assumptions": ["Console sign-ins are recorded as eventType AwsConsoleSignIn"],
    "confidence": 0.95,
    "confidence_reasons": ["valid on first attempt", "1 assumption made (-0.05)"],
    "result_summary": "61 rows · 9 distinct sourceIPAddress · eventTime 2017-02-12 → 2020-01-15"
  },
  "result": { "columns": ["…"], "rows": [["…"]], "row_count": 61, "total_rows": 61, "truncated": false },
  "trace": { "attempts": [{ "attempt": 1, "input_tokens": 9600, "output_tokens": 900, "outcome": "ok" }] },
  "usage": { "tokens_used": 10500, "tokens_remaining": 189500, "resets_at": "2026-10-29T12:00:00Z" }
}
```
**When credits run out:** `429`, with `Retry-After` set to the seconds until the window resets:
```json
{ "error": { "code": "CREDITS_EXHAUSTED", "message": "Token budget exhausted for this window",
             "details": { "tokens_remaining": 0, "resets_at": "2026-10-29T12:00:00Z" } }, "request_id": "req_…" }
```

**Status codes:**

| Code | When |
|---|---|
| 200 | OK, including a generation that failed after its retries (`status: "failed"`, D22) |
| 201 | User created |
| 400 / 401 | Malformed or missing `X-User-Id` |
| 403 | Header user ≠ path user |
| 404 | Unknown user |
| 409 | User exists |
| 422 | Invalid body |
| 429 | `CREDITS_EXHAUSTED` or `CREDITS_CONTENDED`; the LLM is not called |
| 502 / 504 | LLM provider error / LLM or DuckDB timeout |
| 500 | Unexpected; logged with its `request_id`, no internals leaked |

## 7. Business Logic & Edge Cases

### 7.1 Pure rules (`credits/policy.py`, no I/O)
`window_bounds(now)`, `remaining(limit, used)`, `decide_admission(limit, used, in_flight, max_call_tokens)` →
Admit / Exhausted / Contended, and `retry_after_seconds(now, resets_at)`. They are unit-tested at the window
boundaries: 05:59:59, 06:00:00, 23:59:59 and a day rollover.

### 7.2 Request flow: `POST /v1/queries`
1. Guards and DTO validation (401 / 400 / 404 / 422).
2. Insert a `query_requests` row with status `in_progress`.
3. Admit the first LLM call (§7.3). If it's denied, mark the request `rejected` and return **429 without calling the LLM**.
4. Run the harness (§8). Each call is finalized with its actual tokens, and each retry is admitted again.
5. Record the outcome and return the response with `tokens_used` and `tokens_remaining`.

### 7.3 Admission with the in-flight claim
Each admission is one short transaction. The LLM call happens outside it.
1. Lock the user row: `SELECT … FROM users WHERE user_id = :uid FOR NO KEY UPDATE` (D46).
2. Expire this user's `pending` rows older than `PENDING_TTL_S`, so a crashed call can't hold credits forever.
3. Read `used` and `in_flight` (§5).
4. If `remaining ≤ 0`: **Exhausted**. Return 429 with `Retry-After` = seconds until the reset.
5. If `remaining − in_flight × MAX_CALL_TOKENS ≤ 0`: **Contended**. Return 429 with a short `Retry-After`.
6. Otherwise insert a `pending` row and commit, which releases the lock.

`finalize()` then writes the actual tokens and marks the row `completed`, or `failed` with 0 tokens if the LLM reported
no usage.

**Worked example**, with `MAX_CALL_TOKENS` = 15,000, measured from real calls (D37):
```
used 195,000 / 200,000
A: remaining 5,000, in flight 0  → admitted → calls the LLM
B: remaining 5,000, in flight 1  → 5,000 − 15,000 < 0 → 429 CONTENDED
A finishes: 3,500 tokens         → used 198,500
B retries: admitted, 3,500       → used 202,000  (over by at most one call, by design)
C: remaining ≤ 0                 → 429 EXHAUSTED until 12:00Z
```

### 7.4 Edge cases and decided behaviour
| Case | Behaviour |
|---|---|
| Call admitted at 05:59:59, finishes at 06:00:04 | Charged to the 00:00 window (D11) |
| Credits run out during self-correction | Stop; `status: "failed"`, `CREDITS_EXHAUSTED_MIDWAY`, with the tokens spent so far |
| LLM error / timeout | Call `failed` with 0 tokens; 502 / 504. Known risk: the provider may still bill a timeout |
| 0 rows, and every filter value exists | A valid answer, not an error |
| 0 rows because a filter value doesn't exist | Value check → self-correction with the closest real values (§8.2) |
| SQL outside the allowlist | Rejected and fed back for correction; never executed (§8.3) |
| Result bigger than `max_rows` | Truncated; `truncated: true`, and `total_rows` gives the true count |
| Process crashes mid-call | The pending row expires after `PENDING_TTL_S` |
| `WINDOW_HOURS` doesn't divide 24 | The app refuses to start |

## 8. Generation Harness
Small stages with typed inputs and outputs (`harness/stages.py`), wired together by `pipeline.py`, which records a trace:
```
[1] Build prompt  versioned system prompt + schema card + title + hypothesis (+ previous SQL and the problem, on retry)
[2] Generate      structured output → {interpretation, reasoning, assumptions[], sql, output_kind}
[3] Validate      allowlist (§8.3); LIMIT injected or capped
[4] Execute       locked-down DuckDB, in a thread, with timeout and row cap
[5] Value check   if 0 rows: does every filter value exist in its column? (§8.2)
[6] Explain       result summary + confidence (§8.4); no extra LLM call
On a failure at [3]–[5], go back to [1] with the reason, up to 1 + MAX_SELF_CORRECT attempts, each admitted and billed.
```
The stages know nothing about HTTP or credits. The pipeline gets a `CreditGuard` (admit / finalize) for each attempt.
The trace records each attempt's tokens, latency, outcome and error, plus the time spent in each stage.

### 8.1 Prompts as files (D27)
- **Files:** `prompts/<version>/` holds `system.md`, `user_template.md` and `retry_template.md`. Python never
  contains prompt text.
- **Fails fast:** `PromptRegistry` loads the version named by `PROMPT_VERSION` at startup and refuses to start if a
  file or placeholder is missing.
- **Hash:** the registry hashes the files. The hash is stored on every request and run, so any result can be traced
  to its exact prompt text.
- **v1 vs v2:** they sit side by side, so a diff shows exactly what changed.
- **Swappable:** a Langfuse-backed registry can replace the file-based one without touching the harness (§18).

### 8.2 Schema card and zero-row value check (D33, D45)
**Schema card.** `data-prep` builds it once and stores it inside `cloudtrail.duckdb`, so the data and its
description can't drift apart. It holds:
- for columns with 200 or fewer distinct values: the **full value list** (e.g. all 103 `errorCode` values)
- for other columns: the top 30 values
- for opaque IDs: 3 examples
- for `eventTime`: its range

The prompt version lists values without counts, about 9.6K input tokens per call.

**Zero-row value check.** When a query returns 0 rows, the harness checks every literal compared against a column
(`=`, `IN`, `LIKE`). A missing value becomes a correction, for example: *"'UnauthorizedOperation' not found in
errorCode; closest: 'Client.UnauthorizedOperation', …"*. If every value exists, the 0 rows are accepted as the answer.

### 8.3 SQL safety: two layers (D41)
1. **Allowlist validator (sqlglot):**
   - exactly one `SELECT`, CTEs allowed
   - the only table it reads is `cloudtrail` (plus its own CTEs)
   - only the 19 known columns
   - only approved functions
   - a `LIMIT` injected or capped

   Every rejection comes with a reason the LLM can act on.
2. **Locked-down DuckDB:**
   - `read_only`
   - `enable_external_access = false`, so no file or network access
   - `lock_configuration = true`
   - thread and memory limits, plus a per-query timeout

   Tests confirm that `read_csv`, `COPY`, `ATTACH` and `SET` fail even when the validator is bypassed.

### 8.4 Deterministic confidence (D34)
Confidence starts at 1.0. Each deduction below is listed in `confidence_reasons`, and the LLM never rates itself.

| Signal | Deduction |
|---|---|
| Each self-correction | −0.15 |
| 0 rows (values verified) | −0.20 |
| Each declared assumption | −0.05 (max −0.20) |
| Result truncated | −0.05 |
| `output_kind` contradicts the SQL | −0.15 |

## 9. Evaluation Harness
`python main.py` works like an exam for the API:
- It sends each hypothesis through `POST /v1/queries` over **real HTTP**, the way a client would (D38).
- It scores the rows **strictly** against `hypotheses_outcomes.json` and writes a run folder.
- It never changes the model; prompt and harness changes come from reading the results.

**Iteration policy (D29):** a prompt change may only add a rule that holds for **any** hypothesis. Where the answer
key scopes a hypothesis more narrowly than its wording, the gap is explained, not fitted.

### 9.1 Modes
| Command | What it does |
|---|---|
| `python main.py [--only 1,9a]` | Live run: a fresh user (D21), hypotheses in order, one at a time; checks `/healthz` first |
| `python main.py --replay runs/<run>` | Re-scores saved responses; no API or LLM calls |
| `python main.py --compare runs/<a> runs/<b>` | Before/after diff + `evaluation_dashboard.html` |

### 9.2 Official runs (D40)
- **Before:** prompt v1, no self-correction, value check off. v1 is an honest first attempt: the same schema card,
  role and output contract, just without the lessons learned from failures.
- **After:** prompt v2, up to 2 self-corrections, value check on.

### 9.3 Run folder (D19)
Each live run gets a new folder, `runs/<timestamp>_<prompt>/`, holding:
- `run_config.json`: the server's settings from `/healthz`, the prompt hash and the dataset hash
- `responses/<id>.json`
- `evaluation_results.json`, which a full live run also copies to the repo root
- `report.md`

### 9.4 Scoring
**Both sides are normalised the same way first:**
- float IDs become text
- NaN, NULL and empty strings become one null value
- strings are trimmed
- column names are matched case-insensitively and alias-tolerantly (`instanceType` ↔ `requestParametersinstanceType`)
- the count column is found by its name

**How answers are matched:**
- **Event answers:** matched as a multiset, on `eventID` where both sides have it, otherwise on the shared columns.
- **Grouped answers:** matched on the group keys they share with the answer key, regrouped with the counts summed
  (D47).

### 9.5 Composite score (D25)
| Check | Question | Weight |
|---|---|---|
| Ran | Did the SQL run? | 20% |
| Right columns | Overlap (Jaccard) of expected and returned columns | 20% |
| Right rows / groups | F1 of the matched events or groups | 40% |
| Right counts | For grouped answers, the share of matched groups with the exact count | 20% |

- **Event-shaped hypotheses** have no counts, so their weights become 25 / 25 / 50.
- **A failed query** scores 0.
- **Skipped hypotheses** are excluded from the averages and listed.
- **The overall score** is the plain average over hypotheses. Every check is also reported on its own, so the total
  never hides where a query went wrong.
- **Strict only (D30).** Relaxed scoring is future scope.

The scorer was validated before use: the answer key scored against itself gives 1.0 on all 11 hypotheses.

### 9.6 Failure handling during a run (D42)
| Situation | Behaviour |
|---|---|
| Query `failed` | Score 0, continue |
| 429 `CREDITS_CONTENDED` | Wait `Retry-After` once, then retry |
| 429 `CREDITS_EXHAUSTED` | Mark the remaining hypotheses `skipped` |
| 502 / 504 | Retry once, then score 0 |
| Ctrl-C or API unreachable | Keep everything so far; mark the run `incomplete` |

### 9.7 Expected vs found (D35)
For each hypothesis, the report shows:
- the expected, returned, matched, missing and extra counts
- up to 3 example rows each of missing and extra
- an engineer's note where the gap comes from answer-key scoping (`evaluation/notes.json`). Notes are never used for
  scoring or prompting.

## 10. Performance
| Area | Technique |
|---|---|
| Dataset | One-time CSV → native, columnar DuckDB file; skipped while the CSV hash is unchanged |
| DuckDB | One read-only connection; a cursor per query in `asyncio.to_thread`; thread and memory limits; timeout via `interrupt()` |
| LLM | One identical, cacheable system prompt (schema card included); slim schema card took a call from 19.3K to ~10–12K tokens (D45) |
| Credits DB | asyncpg pool; the user lock is held for milliseconds; index-only hot query |
| HTTP | Fully async; gzip; rows capped by `max_rows` |

## 11. Logging, Errors & Config
- **Logging:** structlog JSON, with `request_id` and `user_id` bound through contextvars.
  - Every failure point logs at a fixed level: guard and validator rejections at warning, credit denials at info,
    LLM, DuckDB and DB errors at error, invalid startup config at critical.
  - API keys are never logged, and hypothesis text is cut to 200 characters.
- **Errors:** an `AppError` hierarchy maps every error to the envelope (§6). An unhandled exception becomes a 500 with
  no stack trace.
- **Config:** `.env` is the only source of settings for Compose, the API, the tests and `main.py`. It is validated at
  startup, so a bad value stops the app. Every key, with its default, is in [`.env.example`](.env.example).

## 12. Testing
69 tests, kept minimal on purpose: the brief's required cases plus one per rule. They run against a real Postgres
test database, a scripted `FakeGateway`, a `FakeClock` and a 5-row DuckDB fixture built with the real build code.
- **The brief's rate-limit tests:**
  - within the limit → recorded
  - exhausted → 429 with the LLM call count at 0
  - credits come back after the window boundary
  - concurrent requests can't overspend
  - usage persists across a restart
- **Business rules:** window boundaries, admission decisions, pending-claim expiry, guards (401 / 400 / 403 / 404 /
  422 / 409).
- **Harness:**
  - validator allowlist and DuckDB lockdown
  - value check, self-correction (two billed calls), retries stopped midway
  - deterministic confidence, timeout and row cap
- **Evaluation:** normalisers, matching, the failure handling against a stub API, replay.
- **Live (opt-in, `pytest -m live`):** one real hypothesis through the real LLM and dataset (D43).

## 13. Build Phases
Each phase was built on its own branch and merged through its own PR, after a review:

| Phase | What it built |
|---|---|
| P0 | Scaffold: config, logging, errors, middleware, Docker Postgres |
| P1 | Schema, users, credits and admission, plus the brief's rate-limit tests |
| P2 | Data prep, schema card, validator, locked-down executor, value check |
| P3 | Harness, LLM gateways, confidence, `POST /v1/queries` |
| P4 | Evaluator and the 'before' run |
| P5 | Failure analysis, prompt v2 and the 'after' run |
| P6 | Docs and the dashboard |

## 14. Prompting Strategy
- **One cached system prompt.** The role, the SQL rules, v2's shape and scope rules, the output fields and the schema
  card are the same for every call and every user, so the provider can cache them. Only the short user or retry
  message changes.
- **Real values, not descriptions:** the schema card (§8.2) is what makes value traps solvable.
- **Structured output (D6).** A strict JSON schema is enforced by the provider and validated again with Pydantic.
  Malformed output is treated as a failure the model can correct.
- **Deterministic feedback.** Retry messages come from the validator, DuckDB, the timeout or the value check, never
  from another LLM call. The retry template says: *"keep what was right; fix only what the problem requires."*
- **No few-shot examples.** Examples drawn from the 11 hypotheses would leak the answer key, and invented ones would
  steer every answer's shape. v2 uses short generic rules instead, each traced to a failure pattern (§15).
- **Sampling:** `effort: medium`, with no temperature set (Sonnet 5.5 rejects it). Confidence is not prompted (§8.4).

## 15. Iteration Log
All runs used the same model (`nvidia/nemotron-3.5-super-vl:free`, D44), the same dataset hash and a fresh user with
200K tokens. Scores were recomputed with the final scorer (D49).

| Run | Prompt (hash) | Harness | Score | Ran · Columns · Rows · Counts | Tokens (calls) |
|---|---|---|---|---|---|
| `runs/2026-10-29T19-19-34Z_v1` | v1 (`9cd12dc42e98`) | no self-correction, no value check | **0.501** | 1.00 · 0.26 · 0.49 · 0.00 | 121,673 (11) |
| `runs/2026-10-29T19-33-48Z_v2` | v2 iteration 1 (`1761c0325962`) | 2 self-corrections, value check | 0.715 | 1.00 · 0.49 · 0.75 · 0.36 | 135,114 (12) |
| `runs/2026-10-29T19-39-48Z_v2` | **v2 final** (`a63b974ab7b1`) | 2 self-corrections, value check | **0.794** | 1.00 · 0.58 · 0.82 · 0.67 | 139,770 (12) |

**What failed in v1, and the generic rule v2 added.** No rule names a hypothesis or an answer-key value; this was
checked by grep.

| v1 failure (hypotheses) | v2 rule |
|---|---|
| "Who / how often / with what" questions came back as raw events: no counts, and cut off at 10K rows (4, 5, 7, 8, 9a, 9b) | **Choose the shape:** events for one rare, specific action; grouped counts for who/how-often/with-what questions or a property many events share |
| Extra metrics and extra group columns (1, 4, 8) | Group by the actor + the attributes the hypothesis names; select only those + `COUNT(*) AS count` |
| Events returned with arbitrary column subsets (2, 3, 6, 10) | Return complete events (`SELECT *`) |
| Filters broadened to related create/describe/list actions (3, 6) | Match only the actions that perform the behaviour |
| Values added beyond those named (4) | Use exactly the named values, or the listed value that contains one |
| Invented cut-offs (`HAVING COUNT(*) >= 5`, `LIMIT 100`) (1, 8) | No thresholds, LIMITs or time windows the hypothesis doesn't state |
| 0 rows: failures filtered on `errorCode` (1) | Failed console sign-ins carry only `errorMessage` |

- **Iteration 1 → final:** the shape rule was sharpened, adding "a property that many events share" and "add no
  other group columns".
- **Tried and dropped:** turning a quoted `*` into an anchored `LIKE`. It returns 0 rows on this data.
- **Why iteration stopped:** what remains is answer-key scoping (#1, #4, #8, #9b) or #7's shape choice. More prompt
  rules aimed at those would be fitting the key. #7 has a generic harness fix in §18.

## 16. Challenges & Solutions
- **A coarsened dataset copy** couldn't match the answer key. This was spotted by comparing rows by index, and the
  correct CSV is used instead (D7).
- **Hypothesis words ≠ data values.** Solved with value lists in the schema card and the zero-row value check (§8.2).
- **Tokens per call.** The full schema card made a call 19.3K tokens, about 10 calls per window. A slimmer card
  brought calls to 10–12K, and `MAX_CALL_TOKENS` was then set from those measurements (D37, D45).
- **Lock vs foreign keys.** `FOR UPDATE` blocked the FK checks of concurrent audit inserts; `FOR NO KEY UPDATE`
  doesn't (D46).
- **The scorer caught its own bug.** Its "single integer column is the count" fallback read account IDs as counts.
  Fixed so dataset columns never qualify, and every run was re-scored from its saved responses (D49).
- **Model and key constraints.** Sonnet 5.5 rejects `temperature`, so generation uses `effort` (D6). The available
  API key had a $0 limit, so the gateway became one interface over three providers, and the official runs used a
  free model (D44).
- **The output shape is the model's hardest choice.** The same wording reads as events in one run and as counts in
  another. Two prompt iterations fixed most cases (D50).

## 17. Limitations
- **`X-User-Id` identifies the caller; it doesn't authenticate them.** Production needs real authentication.
- **Credit accounting:**
  - Overshoot of up to one call is by design (D4).
  - `MAX_CALL_TOKENS` is static.
  - A timed-out call is recorded as 0 tokens, even though the provider may have billed it.
- **Single API instance.** Admission is already safe across instances, but DuckDB is local to each one.
- **Strict scoring** penalises answers that are right but scoped or grouped differently from the key. The report
  explains these cases; the score doesn't credit them.
- **The before/after result rests on one run per setup, on a free model.**
  - The gain can't yet be split between the prompt, self-correction and the value check.
  - The production model wasn't measured.
  - The v2 rules were derived from the same 11 hypotheses, with no held-out set.

  §18 plans all three.
- **Confidence reflects execution risk, not meaning.** A clean query can still answer the wrong question.

## 18. Future Scope
- **Truncation feedback:** when an events answer exceeds the row cap, send back "summarise with grouped counts"
  instead of a truncated list. It's generic and would fix #7. It was left out of P5 so the before/after compares
  prompt changes only.
- **Relaxed scoring + diagnosis labels:** a second score that ignores extra columns and rolls groupings up to the
  key's, with labels such as `broader_filter` and `different_grouping`.
- **Ablation with repeated runs:** five setups, each run 3 times with a fresh user, reported as the average with its
  minimum and maximum:
  - A: v1, plain
  - B: v1 + self-correction
  - C: v1 + self-correction + value check
  - D: v2, plain
  - E: v2 with everything on

  Each comparison (A→B, B→C, A→D, D→E) isolates one change, and the repeats show how much scores vary between runs.
  A script would start one server per setup and refuse to run if `/healthz` reports different settings. It's about
  13 new runs, 2–2.5 hours on the free model.
- **Held-out hypotheses:** 3–4 new ones the v2 rules were never tuned on. All have matching events in the data:
  - IAM privilege escalation (`AttachUserPolicy`, `AttachRolePolicy`, `PutUserPolicy`, `CreatePolicyVersion`)
  - snapshot sharing (`ModifySnapshotAttribute`)
  - security groups opened to the internet (`AuthorizeSecurityGroupIngress`)
  - EC2 credential harvesting (`GetPasswordData`, `CreateKeyPair`, `ImportKeyPair`, as grouped counts)

  The answer key would come from reference SQL, be committed and frozen before any run, and be scored separately from
  the official 11.
- **Langfuse:** prompt versions and labels behind the same `PromptRegistry` interface, plus traces of every LLM call
  for cost and latency dashboards. Postgres stays the only authority for credits.
- **Scale-out and operations:**
  - parallel evaluation with bounded concurrency
  - several API replicas with the log data in a shared store
  - reserve-then-settle credits, for zero overshoot
  - Alembic migrations
  - an admin API for changing user limits
- **Smarter harness:**
  - a `lookup_values(column, pattern)` tool the model can call for long-tail values
  - `MAX_CALL_TOKENS` measured at startup with token counting
  - LLM-blended confidence, with a calibration check
  - `main.py --resume`
  - a model A/B comparison
