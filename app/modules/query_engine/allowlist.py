"""What generated SQL may use (D41). Anything not listed here is rejected by the validator.

Functions are matched on sqlglot's expression key (e.g. `ROW_NUMBER()` -> "rownumber") or, for functions
sqlglot doesn't model, on the lowercased DuckDB name. File, network, settings and catalog functions
(read_csv, getenv, duckdb_*, ...) are deliberately absent.
"""

from app.modules.query_engine.dataset import COLUMNS, TABLE

ALLOWED_TABLES: frozenset[str] = frozenset({TABLE})
ALLOWED_COLUMNS: frozenset[str] = frozenset(c.lower() for c in COLUMNS)
COLUMN_BY_LOWER: dict[str, str] = {c.lower(): c for c in COLUMNS}

ALLOWED_FUNCTIONS: frozenset[str] = frozenset({
    # aggregates
    "count", "countif", "sum", "avg", "min", "max", "approxdistinct", "anyvalue", "arrayagg",
    "groupconcat", "median", "mode", "stddev", "stddevpop", "stddevsamp", "variance", "quantile",
    "list", "approx_count_distinct", "string_agg", "count_if",
    # strings
    "lower", "upper", "length", "substring", "trim", "ltrim", "rtrim", "concat", "concatws", "replace",
    "splitpart", "startswith", "endswith", "ends_with", "contains", "strposition", "left", "right", "lpad", "rpad",
    "reverse", "initcap", "len", "string_split", "split",
    # regex
    "regexpextract", "regexplike", "regexpreplace", "regexp_full_match", "regexp_matches",
    # null / conditional / types
    "cast", "trycast", "coalesce", "nullif", "case", "if", "greatest", "least", "ifnull",
    # date / time
    "extract", "timestamptrunc", "datetrunc", "timetostr", "strtotime", "timetounix", "unixtotime",
    "datediff", "dateadd", "timestampdiff", "timestampadd", "datepart", "date_part", "epoch", "strptime",
    "to_timestamp", "currenttimestamp", "currentdate", "date", "timebucket", "time_bucket",
    # math
    "abs", "round", "floor", "ceil", "mod", "power", "sqrt", "ln", "log",
    # window
    "rownumber", "rank", "denserank", "lag", "lead", "firstvalue", "lastvalue", "ntile", "percentrank",
    "cumedist", "nthvalue",
})
