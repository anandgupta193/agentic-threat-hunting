"""Brief entry point: evaluates the API against the answer key over HTTP (see `python main.py --help`)."""

import sys

from evaluation.cli import main

if __name__ == "__main__":
    sys.exit(main())
