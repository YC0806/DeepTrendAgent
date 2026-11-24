#!/usr/bin/env python3
from __future__ import annotations

import argparse
from importlib import import_module
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PACKAGE_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = PACKAGE_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
PACKAGE_NAME = PACKAGE_DIR.name

_cli_common = import_module(f"{PACKAGE_NAME}.scripts._cli_common")
default_snapshot_date = _cli_common.default_snapshot_date
dump_json = _cli_common.dump_json
init_run_layout = _cli_common.init_run_layout


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Initialize a DeepTrend run directory and emit its canonical layout."
    )
    parser.add_argument("--source", default="github-trending")
    parser.add_argument("--since", default="daily")
    parser.add_argument("--language", default="all")
    parser.add_argument("--artifact-root", help="Override settings.deeptrend_artifact_root.")
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = init_run_layout(
        snapshot_date=default_snapshot_date(),
        source=args.source,
        since=args.since,
        language=args.language,
        artifact_root=args.artifact_root,
    )
    print(dump_json(payload, pretty=args.pretty))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
