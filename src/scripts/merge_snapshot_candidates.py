from __future__ import annotations

import argparse

from ..models import TrendingSnapshot
from ..tools.github.github_diff import merge_new_entries
from ._cli_common import dump_json, load_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge new entries from supplemental snapshots in the given order.")
    parser.add_argument("--primary", required=True)
    parser.add_argument("supplements", nargs="+")
    args = parser.parse_args()

    primary = TrendingSnapshot.from_dict(load_json(args.primary))
    supplements = (TrendingSnapshot.from_dict(load_json(path)) for path in args.supplements)
    candidates = merge_new_entries(primary, supplements)
    print(dump_json([entry.to_dict() for entry in candidates], pretty=False))


if __name__ == "__main__":
    main()
