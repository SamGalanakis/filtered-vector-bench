#!/usr/bin/env python3
"""Generate charts and summary Markdown from benchmark results."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fvb.report import generate_report  # noqa: E402


def main() -> None:
    """Parse CLI arguments and generate report artifacts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument(
        "--compare", type=Path, action="append", default=[],
        help="additional result directory supplying another measurement state",
    )
    args = parser.parse_args()
    generate_report(args.results.resolve(), [path.resolve() for path in args.compare])
    print((args.results.resolve() / "summary.md"))


if __name__ == "__main__":
    main()
