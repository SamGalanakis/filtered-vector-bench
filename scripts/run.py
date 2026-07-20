#!/usr/bin/env python3
"""Run a filtered vector benchmark matrix."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fvb.config import load_config  # noqa: E402
from fvb.runner import run_benchmark  # noqa: E402


def main() -> None:
    """Parse CLI arguments and execute the benchmark."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/default.yaml")
    parser.add_argument("--engine", choices=("surrealdb", "postgres", "all"), default="all")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    output = args.out or ROOT / "results" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    config = load_config(args.config.resolve())
    engines = tuple(config.engines) if args.engine == "all" else (args.engine,)
    run_benchmark(config, output.resolve(), engines)
    print(output.resolve())


if __name__ == "__main__":
    main()
