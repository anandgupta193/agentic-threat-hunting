"""One-time job (the `data-prep` compose service, or `make prepare-data`): CSV -> data/cloudtrail.duckdb.

Skips the work when the stored CSV hash matches. Exit code 1 with a clear message if the CSV is missing.
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.core.logging import configure_logging, get_logger  # noqa: E402
from app.modules.query_engine.dataset import build_database  # noqa: E402

DATASET_URL = "https://www.kaggle.com/datasets/nobukim/aws-cloudtrails-dataset-from-flaws-cloud"


def main(force: bool) -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    log = get_logger("prepare_data")
    csv_path, db_path = settings.dataset_csv_path, settings.duckdb_path
    if not csv_path.exists():
        log.critical("dataset_csv_missing", path=str(csv_path),
                     hint=f"Download nineteenFeaturesDf.csv ({DATASET_URL}) into ./data/")
        return 1
    t0 = time.perf_counter()
    info = build_database(
        csv_path, db_path, max_distinct=settings.schema_card_max_distinct, top_n=settings.schema_card_top_n,
        memory_limit=settings.duckdb_memory_limit, threads=settings.duckdb_threads, force=force,
    )
    log.info("dataset_ready", rebuilt=info.rebuilt, rows=info.row_count, db=str(db_path),
             csv_sha256=info.csv_sha256[:12], seconds=round(time.perf_counter() - t0, 1))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="rebuild even if the CSV hash is unchanged")
    sys.exit(main(parser.parse_args().force))
