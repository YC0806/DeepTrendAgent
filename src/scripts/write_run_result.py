from __future__ import annotations

import argparse
import json
import sys

from ..models import Delivery, RepoAnalysis, SupplementalCandidate, TrendReport, TrendRun, TrendingSnapshot, utcnow_iso
from ._cli_common import load_json, resolve_run_dir, write_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Write a run result or record its delivery handoff from JSON on stdin.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--delivery", action="store_true", help="Update the existing result with a Delivery object.")
    args = parser.parse_args()
    run_dir = resolve_run_dir(args.run_dir)
    if run_dir is None:
        parser.error("--run-dir must be nonempty")

    result_path = run_dir / "result.json"
    try:
        payload = json.load(sys.stdin)
        if args.delivery:
            run = TrendRun.from_dict(load_json(str(result_path)))
            run.delivery = Delivery.from_dict(payload)
        else:
            run = TrendRun(
                run_id=run_dir.name,
                run_dir=str(run_dir),
                snapshot=TrendingSnapshot.from_dict(load_json(str(run_dir / "snapshot.json"))),
                analyses=[RepoAnalysis.from_dict(item) for item in payload["analyses"]],
                report=TrendReport(
                    generated_at=utcnow_iso(),
                    summary=payload["summary"],
                    markdown=(run_dir / "report.md").read_text(encoding="utf-8"),
                    statistics=payload["statistics"],
                ),
                supplemental_candidates=[
                    SupplementalCandidate.from_dict(item) for item in payload["supplemental_candidates"]
                ],
            )
        write_json(result_path, run.to_dict(), pretty=True)
    except (KeyError, OSError, TypeError, ValueError) as exc:
        print(f"write_run_result failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
