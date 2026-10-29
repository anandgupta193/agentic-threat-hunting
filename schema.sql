-- Credit store schema (Postgres 16). Applied idempotently at API startup (APPROACH §5).
-- All timestamps are TIMESTAMPTZ in UTC. This file is the source of truth; ORM models mirror it.

CREATE TABLE IF NOT EXISTS users (
  user_id      VARCHAR(64) PRIMARY KEY CHECK (user_id ~ '^[A-Za-z0-9_.-]{1,64}$'),
  token_limit  INTEGER     NOT NULL CHECK (token_limit > 0),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per POST /v1/queries that reached the credit check (audit trail).
CREATE TABLE IF NOT EXISTS query_requests (
  request_id      VARCHAR(40)  PRIMARY KEY,
  user_id         VARCHAR(64)  NOT NULL REFERENCES users(user_id),
  hypothesis      TEXT         NOT NULL,
  status          VARCHAR(16)  NOT NULL CHECK (status IN ('in_progress','succeeded','failed','rejected')),
  error_code      VARCHAR(40),
  final_sql       TEXT,
  confidence      NUMERIC(3,2) CHECK (confidence BETWEEN 0 AND 1),
  row_count       INTEGER      CHECK (row_count >= 0),
  attempts        SMALLINT     NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  prompt_version  VARCHAR(16),
  prompt_hash     CHAR(12),
  model           VARCHAR(64),
  latency_ms      INTEGER,
  created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
  completed_at    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_qr_user_created ON query_requests (user_id, created_at DESC);

-- One row per LLM call: the billing unit. `pending` is the in-flight claim taken at admission (§7.3).
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
-- Covering index for the hot "used this window" query: answered by an index-only scan.
CREATE INDEX IF NOT EXISTS ix_tu_user_window ON token_usage (user_id, window_start)
  INCLUDE (input_tokens, output_tokens, status);
