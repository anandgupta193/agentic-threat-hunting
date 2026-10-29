"""`python main.py` command line (§9.1)."""

import argparse
import sys
from pathlib import Path

import httpx

from app.core.config import Settings
from evaluation.loaders import ROOT, load_expected, load_hypotheses
from evaluation.runner import ApiUnreachable, LiveRunner, compare, replay

RUNS_DIR = ROOT / "runs"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="main.py", description="Evaluate the query generator against the "
                                     "answer key, over HTTP against the running API.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--replay", type=Path, metavar="RUN_DIR", help="re-score a saved run (no API calls)")
    mode.add_argument("--compare", type=Path, nargs=2, metavar=("BEFORE", "AFTER"), help="before/after diff")
    parser.add_argument("--only", help="comma-separated hypothesis ids, e.g. 1,9a")
    parser.add_argument("--token-limit", type=int, help="token limit for the run's fresh user (default: the "
                        "server's TOKEN_LIMIT_DEFAULT)")
    parser.add_argument("--base-url", help="API base URL (default: API_BASE_URL from .env)")
    args = parser.parse_args(argv)

    if args.compare:
        out, text = compare(*args.compare)
        print(text)
        print(f"Saved {out}", file=sys.stderr)
        return 0

    hypotheses = load_hypotheses()
    expected = load_expected()
    if args.only:
        wanted = {x.strip() for x in args.only.split(",")}
        if unknown := wanted - {h.id for h in hypotheses}:
            parser.error(f"unknown hypothesis ids: {', '.join(sorted(unknown))}")
        hypotheses = [h for h in hypotheses if h.id in wanted]

    if args.replay:
        folder, results = replay(args.replay, hypotheses, expected, RUNS_DIR)
    else:
        base_url = args.base_url or Settings().api_base_url
        with httpx.Client(base_url=base_url, timeout=30) as client:
            runner = LiveRunner(client, hypotheses, expected, RUNS_DIR, token_limit=args.token_limit,
                                copy_to_root=not args.only)
            try:
                folder, results = runner.run()
            except ApiUnreachable as exc:
                print(exc, file=sys.stderr)
                return 1
    ov = results["overall"]
    score = "–" if ov["score"] is None else f"{ov['score']:.3f}"
    print(f"Overall score {score} ({ov['scored']} scored, {ov['failed']} failed, {ov['errors']} errors, "
          f"{len(ov['skipped'])} skipped) → {folder}/report.md")
    return 1 if results["run"].get("incomplete") else 0
