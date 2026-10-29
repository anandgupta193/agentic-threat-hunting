# DECISIONS: Decision Log

> Internal working log for this project. `APPROACH.md` is the reviewer-facing design document; this file records **every decision, why it was made, and what it replaced**.
> Status: **Planning**. No code has been written yet.

**How this log is maintained**
- Each decision gets a stable ID (`D<n>`). IDs are never reused or renumbered.
- A changed decision is not edited away. The old choice moves to [Superseded](#superseded-decisions) with the reason, and the active row is updated.
- Status: ✅ agreed · 🟡 proposed (awaiting sign-off) · ❌ rejected.
- `APPROACH.md` cites these IDs (e.g. "D4") where a design choice needs justification.

---

## Active Decisions
| # | Area | Decision | Why / trade-off | Status | Date |
|---|---|---|---|---|---|
| D1 | Framework | FastAPI, async/await throughout, Python 3.12 | Native async and DI via `Depends`; Pydantic v2 DTOs | ✅ | 2026-10-29 |
| D2 | Credit DB | **Postgres 16 in Docker** (docker-compose), async driver `asyncpg` | Real row-level locking (`SELECT … FOR UPDATE`) for the concurrency rule; data lives in a named volume, so it survives API and container restarts; same engine for dev and tests | ✅ | 2026-10-29 |
| D3 | Log query engine | DuckDB embedded in the API process, over a native `cloudtrail.duckdb` file (see D39, D41) | Fast columnar analytics; SQL is easy to validate. Sync library, so it runs in `asyncio.to_thread` | ✅ | 2026-10-29 |
| D4 | Overspend policy | "Let it finish, block the next" + **in-flight claim** | Overshoot capped at 1 call; concurrent calls can't both spend the last credits; DB lock held for milliseconds, never during the LLM call | ✅ | 2026-10-29 |
| D5 | Architecture | Modular monolith: modules talk only through service interfaces | Clear boundaries, easy to test and to split later | ✅ | 2026-10-29 |
| D6 | LLM | Claude Sonnet 5.5 (`claude-sonnet-5-5`), model and `LLM_EFFORT` (default `medium`) set in `.env`; **structured outputs** (`output_config.format` = JSON schema) for the generation contract; no sampling params | Good SQL quality for the cost. Sonnet 5.5 rejects forced `tool_choice` and non-default `temperature`, so schema-constrained output replaces tool use and effort replaces temperature. Tokens come from the reported usage | ✅ | 2026-10-29 |
| D7 | Dataset | `nineteenFeaturesDf.csv`, converted once into `data/cloudtrail.duckdb` (D39) | The brief requires it and it matches the answer key row for row | ✅ | 2026-10-29 |
| D8 | Answer key never shown to the LLM | Generator sees only the hypothesis + schema card | Avoids leakage; evaluation stays honest | ✅ | 2026-10-29 |
| D9 | Cached input tokens | `input_tokens + cache_read + cache_creation` all count toward credits | "Count what the LLM reports"; conservative | ✅ | 2026-10-29 |
| D10 | Window math | `window_start = UTC midnight + floor(elapsed / window_len) × window_len`. Window length must divide 24h; checked at startup | Gives the exact 00/06/12/18 boundaries; bad config fails fast | ✅ | 2026-10-29 |
| D11 | Window of a call that spans a boundary | Charged to the window in which it was **admitted** | Deterministic; no split accounting | ✅ | 2026-10-29 |
| D12 | Self-correction retries | Each retry is its own LLM call with its own `token_usage` row, goes through admission again, and is **billed to the user** (no configurable switch) | The brief says "every LLM call spends credits"; the limit protects LLM capacity, which is spent either way; free retries would be an abuse loophole (up to 3× budget). Reconsidered on 2026-10-29 and confirmed | ✅ | 2026-10-29 |
| D13 | Reading credits/usage | `X-User-Id` must equal the path `user_id`, else 403 | No cross-user data leaks. The header is identification, not authentication | ✅ | 2026-10-29 |
| D14 | LLM credentials | Anthropic **API key** in `.env` | The Claude Code login can't be used by the app | ✅ | 2026-10-29 |
| D15 | Schema source of truth | Hand-written `schema.sql` (`CREATE … IF NOT EXISTS`), applied idempotently by the API at startup; **no Alembic** | Easy for reviewers to read; no migration tooling to explain. Applying it from the app (rather than Postgres's init folder) also works on an existing volume | ✅ | 2026-10-29 |
| D16 | DB access style | **SQLAlchemy 2.0 async ORM** over `asyncpg`; typed `Mapped[]` models per module mirroring `schema.sql`; no `create_all`; `expire_on_commit=False`; relationships `lazy="raise"`; explicit `select()` (with `with_for_update()`) on hot paths | Readable, typed domain models; the rules avoid the usual async-ORM pitfalls (hidden lazy loads, expired attributes); `schema.sql` stays the single source of truth | ✅ | 2026-10-29 |
| D17 | Audit table | Add **`query_requests`**: one row per API request, linked to its N LLM calls in `token_usage` | Traceability: "what did this request do and cost?" | ✅ | 2026-10-29 |
| D18 | Evaluation execution | **Sequential**, one hypothesis at a time | Simple, deterministic and easy to debug; parallel runs moved to future scope | ✅ | 2026-10-29 |
| D19 | Run storage | Every run writes a new **timestamped folder** `runs/<UTC timestamp>_<prompt_version>/` | Reproducible before/after comparisons | ✅ | 2026-10-29 |
| D20 | Replay mode | `--replay <run_dir>` re-scores saved responses with **no** API or LLM calls | Lets the scoring code change without spending credits | ✅ | 2026-10-29 |
| D21 | User per evaluation run | Each live run creates a **fresh user** (`eval-<timestamp>`) | The brief says one user per run; a fresh budget per run keeps before/after comparable | ✅ | 2026-10-29 |
| D22 | Generation failed after retries | HTTP **200** with `status: "failed"`, the last SQL, the error and the tokens spent | A business outcome, not a transport error; the evaluator scores it 0. Provider failures use 502/504 | ✅ | 2026-10-29 |
| D23 | Creating a user | `POST /v1/users` does **not** need `X-User-Id`; `user_id` is optional in the body (server generates `usr_<uuid>` if missing) | You can't identify as a user that doesn't exist yet | ✅ | 2026-10-29 |
| D24 | Documentation split | `APPROACH.md` = reviewer-facing design; `DECISIONS.md` = full decision log + open questions | Keeps the reviewer document clean; the reasoning trail is still available | ✅ | 2026-10-29 |
| D25 | Composite score | Ran 20% · right columns 20% · right rows/groups (F1) 40% · right counts 20%. Not run → 0. Row-shaped hypotheses have no counts, so the weights are rescaled to 25/25/50. Skipped (no credits) → excluded. Overall = macro average; each check is also reported separately | Right events matter most; partial credit makes progress between versions visible; macro average treats every hypothesis equally | ✅ | 2026-10-29 |
| D26 | Local Postgres | The project runs its **own** Postgres via its own `docker-compose.yml` (`COMPOSE_PROJECT_NAME=threat-hunt`, volume `threat_hunt_pgdata`), host port `POSTGRES_PORT` default **5433**. `.env` is the single config source; `DATABASE_URL` optionally points to an external Postgres | Evaluators can run it with `cp .env.example .env` + `make up`; no clash with an existing Postgres on 5432; never touches other projects' databases (e.g. the existing LiteLLM Postgres) | ✅ | 2026-10-29 |
| D27 | Prompt storage | Prompts kept as **files** in `prompts/<version>/` (`system.md`, `user_template.md`, `retry_template.md`), loaded by a file-based `PromptRegistry` chosen by `PROMPT_VERSION`; version + content hash recorded per request and per run | Prompts are reviewable and diffable separately from code; the exact prompt behind every result is traceable; easy to swap for a hosted registry later | ✅ | 2026-10-29 |
| D28 | Prompt versioning & LLM monitoring (future) | **Langfuse** in future scope: prompt management behind the same `PromptRegistry` interface, plus tracing of tokens, latency and cost via an observer hook in `LLMGateway` | Production-grade versioning and monitoring without redesign; Postgres remains the source of truth for credit enforcement | ✅ (future) | 2026-10-29 |
| D29 | Iteration policy (grill Q1) | **Generalise, and report the gap honestly.** Prompt/harness changes may only add rules valid for any hypothesis; nothing targets a specific hypothesis or the answer key. Answer-key scoping quirks (e.g. #1) are explained in the report | Avoids overfitting to 11 test cases; the brief forbids hardcoded detections; shows judgement | ✅ | 2026-10-29 |
| D30 | Scoring mode (Q2) | **Strict score only** (the D25 composite against the answer key as given) | Simple, honest and unarguable. Relaxed scoring + diagnosis labels → future scope | ✅ | 2026-10-29 |
| D31 | Execution in the API (Q3) | The API always executes the SQL internally (self-correction needs runtime errors). Request flag **`include_results`** (default `true`) controls only whether rows are returned | Runtime errors get fixed; clients that run SQL themselves can skip the payload | ✅ | 2026-10-29 |
| D32 | Request input (Q4) | `hypothesis` (required) + optional **`title`**; **no `id`** | The title carries analyst intent; it comes from the hypothesis file, not the answer key. No `id` means no answer-key-specific logic | ✅ | 2026-10-29 |
| D33 | LLM data context (Q5) | **Static schema card**: full value lists for columns with ≤ 200 distinct values, top 30 for the rest, plus data conventions. **Zero-row value check**: if 0 rows and a filter literal doesn't exist, retry with the closest real values (billed per D12) | Catches traps like `UnauthorizedOperation` vs `Client.UnauthorizedOperation`; one LLM call per attempt. Agentic lookup tool → future scope | ✅ | 2026-10-29 |
| D34 | Confidence (Q6) | **Deterministic, computed by the harness** from objective signals (retries, zero rows, assumptions, truncation, shape mismatch), reasons listed; weights in config. The LLM does not rate itself | Explainable and repeatable. LLM blend + calibration check → future scope | ✅ | 2026-10-29 |
| D35 | Results vs expected findings (Q7) | API: deterministic `result_summary`. Report: per-hypothesis **expected vs found** (matched/missing/extra + up to 3 examples each) | Covers the brief's "how results map to expected findings" without showing the answer key to the system | ✅ | 2026-10-29 |
| D36 | Table exposed to the LLM (Q8) | A `cloudtrail` view with **exactly the 19 original columns, all `VARCHAR`**, values as in the CSV, empty → `NULL`. `row_idx` hidden; the validator rejects anything else | `SELECT *` matches the answer key; no type-inference surprises; strict scoring stays fair | ✅ | 2026-10-29 |
| D37 | `MAX_CALL_TOKENS` | Static **15,000**, measured in P3: with the slimmed schema card, real calls used 10.3K–12.3K tokens (input ≈ 9.6K, output 0.7K–2.8K) on the free model | Simple and explainable; overshoot stays bounded by one call (D4). Measuring at startup is future scope | ✅ | 2026-10-29 |
| D38 | `main.py` target (Q11) | **Real HTTP only** to `API_BASE_URL`; fails fast via `/healthz` if unreachable. In-process client only inside tests | The most literal reading of "through POST /v1/queries"; one code path | ✅ | 2026-10-29 |
| D39 | Data preparation (Q12) | One-time **`data-prep` compose service** builds `data/cloudtrail.duckdb` + the schema card, skips if the CSV hash is unchanged; `api` waits for it. CSV lives in `./data/` (gitignored). `make prepare-data` for non-Docker runs | `make up` just works for evaluators; conversion logic stays out of the API | ✅ | 2026-10-29 |
| D40 | Before/after runs (Q10) | **Two official runs**: before = prompt v1, `MAX_SELF_CORRECT=0`, value check off; after = prompt v2 + all features on. v1 must be an honest first attempt | Simple, clear before/after. Ablation ladder → future scope | ✅ | 2026-10-29 |
| D41 | SQL safety (Q14) | **Allowlist validator** (one SELECT/WITH, only `cloudtrail`, only 19 columns, approved functions, LIMIT capped) **+ locked-down DuckDB** (`read_only`, `enable_external_access=false`, `lock_configuration=true`, threads/memory limits, timeout) | Defence in depth; clear errors for self-correction; safe even if the validator has a gap | ✅ | 2026-10-29 |
| D42 | `main.py` failure handling (Q15) | `failed` → 0 and continue; EXHAUSTED → stop, rest `skipped`; CONTENDED → wait once; 502/504 → retry once, then `error`; unreachable/Ctrl-C → stop, run marked `incomplete` | Never wastes a whole run on one hiccup; always an honest record. `--resume` → future scope | ✅ | 2026-10-29 |
| D43 | LLM in tests (Q13) | `FakeGateway` by default + **one opt-in `pytest -m live`** test (skipped without an API key) | Fakes prove the logic; one live test proves the Anthropic contract (usage fields, structured-output shape) | ✅ | 2026-10-29 |
| D44 | LLM provider | `LLM_PROVIDER` switch behind the `LLMGateway` interface: `anthropic` (Anthropic API key; default for evaluators), `openrouter` (OpenRouter API key; default model `anthropic/claude-sonnet-5.5`. The developer's key has a $0 limit, so their `.env` pins the free `nvidia/nemotron-3.5-super-vl:free`, which supports structured outputs. A pinned model, never the `openrouter/free` router, so runs stay comparable) and `claude_code` (local Claude Code CLI in headless mode on the developer's own subscription; dev only). Both use the same JSON-schema contract and report usage that is billed the same way (D9) | The developer has a Claude subscription but no API key. The subscription token is never extracted or used against the API directly; the CLI is used as-is. `claude_code` is slower (one process per call) and only runs where the CLI is installed and logged in, so not inside the Docker image | ✅ | 2026-10-29 |
| D45 | Schema card in the prompt | **Slim rendering**: value names without counts; 3 examples for opaque ID columns (`userIdentityprincipalId`, `userIdentityaccessKeyId`, `userIdentityaccountId`); `eventTime` as a range. The stored card keeps every value and count for the zero-row value check | The full card made one call 19.3K tokens, so ~10 calls fit in a 200K window. Slim: input 17.7K → 9.6K per call. The value check still sees full lists, so the safety net is unchanged | ✅ | 2026-10-29 |

---

## Superseded Decisions
| # | Was | Replaced by | Reason |
|---|---|---|---|
| D2 | SQLite with a Postgres fallback; then SQLite only | Postgres 16 in Docker | Real row locks for the concurrency rule; runs in Docker as requested |
| D4 | Considered: reserve-then-settle | Let it finish + in-flight claim | Simpler, needs no token estimate up front; overshoot bounded to one call. Reserve-then-settle kept as future scope |
| D7 | `dec12_18features.csv` (coarsened: month-only times, 2-octet IPs, truncated user agents, no `requestID`) | `nineteenFeaturesDf.csv` | Coarsened data could not match the answer key; 9a/9b were impossible |
| D18 | Parallel evaluation with a concurrency limit | Sequential | Simpler and deterministic; parallel moved to future scope |
| D16 | Proposed: SQLAlchemy Core (no ORM) | SQLAlchemy 2.0 async ORM | User preference for ORM models; pitfalls handled by explicit usage rules |
| D26 | Considered: reusing the existing `litellm-gateway-db-1` Postgres | Dedicated compose Postgres | It belongs to another project, its port isn't published to the host, and sharing it would mix data; rejected by user |
| D12 | Considered: not billing retries (`RETRY_BILLING=absorb` switch), since retries are often caused by system errors | Always bill | Simpler; matches the brief literally; cost transparency comes from the per-attempt rows in `/usage` instead |
| D3 | Considered: DuckDB in its own executor container | Embedded in the API process | Fewer moving parts; untrusted SQL is contained by the validator + read-only connection instead |
| D3/D7 | DuckDB over a Parquet file | Native `cloudtrail.duckdb` file | `enable_external_access=false` (D41) blocks reading Parquet files at query time; the native format is equally columnar and fast |
| D20/D38 | `main.py` could run the app in-process when `API_BASE_URL` was unset | Real HTTP only | One code path; true end-to-end evaluation |
| D34 | LLM-reported `confidence` + `confidence_reason` in the tool output | Harness-computed deterministic confidence | LLM self-ratings are poorly calibrated; deterministic is explainable |
| D37 | `MAX_CALL_TOKENS=8000` placeholder | 12,000 (static) | The schema card with full value lists makes calls larger |
| D37 | 12,000 (static estimate) | 15,000 (measured) | A real call with the full schema card used 19.3K tokens; after slimming the card (D45), calls used 10.3K–12.3K |
| D36 | Parsed `TIMESTAMP` column next to the original string | All 19 columns as text, no helper columns | Helper columns would break strict `SELECT *` matching |
| D41 | Denylist validator | Allowlist + locked-down DuckDB | Anything not on a denylist slips through; the allowlist fails closed |
| D6 | Tool use (forced `tool_choice`) for structured output + `temperature=0` | Structured outputs (`output_config.format`) + `LLM_EFFORT` | Both are rejected with a 400 by `claude-sonnet-5-5`; found while building the gateway |

---

## Open Questions
- [x] ~~Grilling session (15 questions)~~: resolved as D29–D43 (2026-10-29).
- [x] ~~Sign off D15, D16, D17~~: D15 hand-written schema ✅, D16 ORM ✅, D17 audit table ✅ (2026-10-29).
- [x] ~~Composite score weights~~: agreed as D25 (2026-10-29).
- [ ] Outstanding HR/engineering clarifications (scope, whether retries count against the budget).

---

## APPROACH.md Change History
| Version | Change |
|---|---|
| v0.1 | First full plan (Postgres + SQLite fallback, `dec12_18features.csv`) |
| v0.2 | Switched to `nineteenFeaturesDf.csv`; evaluator normalisation simplified |
| v0.3 | Refocused on harness, DB schema, APIs and business logic; sequential evaluation, run folders, replay |
| v0.4 | Postgres in Docker |
| v0.5 | Decision log and open questions moved to this file; APPROACH.md made reviewer-facing |
| v0.6 | D15/D16/D17 agreed: hand-written schema, async ORM with usage rules, audit table |
| v0.7 | Composite score weights agreed (D25), added as §9.5 |
| v0.8 | Dedicated docker-compose Postgres on port 5433, `.env` as the single config source, evaluator quick start (D26) |
| v0.9 | Prompts as versioned files + `PromptRegistry` (§8.1, D27); Langfuse added to future scope (D28) |
| v1.0 | Grilling outcomes D29–D43: iteration policy, strict scoring, `include_results`/`title`, schema card + zero-row value check, deterministic confidence, expected-vs-found, 19-column text view, static `MAX_CALL_TOKENS`=12K, two runs, real-HTTP `main.py`, `data-prep` service + `.duckdb`, allowlist + locked-down DuckDB, failure handling, opt-in live test; new future-scope items |
| v1.1 | D6 updated (structured outputs, effort instead of temperature); D44 dual LLM provider (`anthropic` / `claude_code`) |
| v1.2 | D44: added the `openrouter` provider |
| v1.3 | D44: developer runs use the free `nvidia/nemotron-3.5-super-vl:free` model via OpenRouter |
| v1.4 | P2 findings: 1,939,207 records (not 1,939,214 lines), corrected cardinalities; schema card stored in `_meta`, `eventTime` described by its range |
| v1.5 | P3: D45 slim schema card in the prompt; D37 `MAX_CALL_TOKENS` measured → 15,000; schema card moved into `system.md` (cache-friendly) |
