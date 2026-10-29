"""Builds `cloudtrail.duckdb` from the CSV (D3, D36, D39) and the schema card stored inside it (D33).

Layout of the built file:
- `events`: the CSV verbatim, every column VARCHAR, rows in file order (`rowid` = 0-based CSV row = answer-key index)
- `cloudtrail`: view over the 19 columns; the only relation generated SQL may read
- `_meta`: key/value build metadata (CSV hash, row count, build version) and the schema card JSON

The build writes to a temp file and renames it into place, so a reader never sees a half-built file.
"""

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

BUILD_VERSION = "2"
TABLE = "cloudtrail"
COLUMNS: tuple[str, ...] = (
    "eventID", "eventTime", "sourceIPAddress", "userAgent", "eventName", "eventSource", "awsRegion",
    "eventVersion", "userIdentitytype", "eventType", "requestID", "userIdentityaccountId",
    "userIdentityprincipalId", "userIdentityarn", "userIdentityaccessKeyId", "userIdentityuserName",
    "errorCode", "errorMessage", "requestParametersinstanceType",
)
IDENTIFIER_DISTINCT_RATIO = 0.5  # columns this unique (eventID, requestID) get examples, not frequency lists
IDENTIFIER_EXAMPLES = 3
TIME_COLUMN = "eventTime"  # ISO-8601 text; described by its range, not by frequent values
HASH_CHUNK = 8 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class BuildInfo:
    rebuilt: bool
    row_count: int
    csv_sha256: str


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(HASH_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def read_meta(db_path: Path) -> dict[str, str]:
    if not db_path.exists():
        return {}
    try:
        with duckdb.connect(str(db_path), read_only=True) as con:
            return dict(con.execute("SELECT key, value FROM _meta").fetchall())
    except duckdb.Error:
        return {}


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def build_schema_card(con: duckdb.DuckDBPyConnection, *, max_distinct: int, top_n: int) -> dict[str, Any]:
    row_count = con.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0]  # type: ignore[index]
    columns = []
    for col in COLUMNS:
        nulls, distinct = con.execute(
            f"SELECT COUNT(*) - COUNT({_q(col)}), COUNT(DISTINCT {_q(col)}) FROM {TABLE}"
        ).fetchone()  # type: ignore[misc]
        if col == TIME_COLUMN:
            lo, hi = con.execute(f"SELECT MIN({_q(col)}), MAX({_q(col)}) FROM {TABLE}").fetchone()  # type: ignore[misc]
            columns.append({
                "name": col, "type": "VARCHAR", "kind": "timestamp",
                "null_rate": round(nulls / row_count, 4) if row_count else 0.0,
                "distinct": distinct, "values_complete": False, "values": [], "min": lo, "max": hi,
            })
            continue
        if distinct <= max_distinct:
            kind, limit = "categorical", max_distinct
        elif row_count and distinct / row_count >= IDENTIFIER_DISTINCT_RATIO:
            kind, limit = "identifier", IDENTIFIER_EXAMPLES
        else:
            kind, limit = "high_cardinality", top_n
        values = con.execute(
            f"SELECT {_q(col)}, COUNT(*) AS n FROM {TABLE} WHERE {_q(col)} IS NOT NULL "
            f"GROUP BY 1 ORDER BY n DESC, 1 LIMIT {limit}"
        ).fetchall()
        columns.append({
            "name": col, "type": "VARCHAR", "kind": kind,
            "null_rate": round(nulls / row_count, 4) if row_count else 0.0,
            "distinct": distinct,
            "values_complete": kind == "categorical",
            "values": [{"value": v, "count": n} for v, n in values],
        })
    return {"table": TABLE, "row_count": row_count, "columns": columns}


def build_database(csv_path: Path, db_path: Path, *, max_distinct: int = 200, top_n: int = 30,
                   memory_limit: str = "2GB", threads: int = 4, force: bool = False) -> BuildInfo:
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)
    csv_hash = file_sha256(csv_path)
    meta = read_meta(db_path)
    if not force and meta.get("csv_sha256") == csv_hash and meta.get("build_version") == BUILD_VERSION:
        return BuildInfo(rebuilt=False, row_count=int(meta["row_count"]), csv_sha256=csv_hash)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = db_path.with_suffix(".duckdb.tmp")
    tmp_path.unlink(missing_ok=True)
    with duckdb.connect(str(tmp_path), config={"memory_limit": memory_limit, "threads": threads}) as con:
        con.execute("SET preserve_insertion_order = true")
        con.execute(
            "CREATE TABLE events AS SELECT * FROM read_csv(?, header = true, all_varchar = true, "
            "auto_detect = true, quote = '\"', escape = '\"')",
            [str(csv_path)],
        )
        found = [r[0] for r in con.execute("DESCRIBE events").fetchall()]
        if found != list(COLUMNS):
            raise ValueError(f"CSV columns do not match the expected 19 columns: {found}")
        con.execute(f"CREATE VIEW {TABLE} AS SELECT {', '.join(_q(c) for c in COLUMNS)} FROM events")
        card = build_schema_card(con, max_distinct=max_distinct, top_n=top_n)
        con.execute("CREATE TABLE _meta (key VARCHAR PRIMARY KEY, value VARCHAR)")
        con.executemany("INSERT INTO _meta VALUES (?, ?)", [
            ("build_version", BUILD_VERSION),
            ("csv_sha256", csv_hash),
            ("row_count", str(card["row_count"])),
            ("built_at", datetime.now(UTC).isoformat()),
            ("schema_card", json.dumps(card)),
        ])
        con.execute("CHECKPOINT")
    os.replace(tmp_path, db_path)
    return BuildInfo(rebuilt=True, row_count=card["row_count"], csv_sha256=csv_hash)
