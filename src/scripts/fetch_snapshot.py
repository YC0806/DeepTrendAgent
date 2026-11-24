#!/usr/bin/env python3
from __future__ import annotations

import argparse
from importlib import import_module
import sys
from datetime import date
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PACKAGE_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = PACKAGE_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
PACKAGE_NAME = PACKAGE_DIR.name

_cli_common = import_module(f"{PACKAGE_NAME}.scripts._cli_common")
models = import_module(f"{PACKAGE_NAME}.models")
provider = import_module(f"{PACKAGE_NAME}.provider")
tools = import_module(f"{PACKAGE_NAME}.tools")
github_trending = import_module(f"{PACKAGE_NAME}.tools.github.github_trending")

dump_json = _cli_common.dump_json
load_json = _cli_common.load_json
parse_run_id = _cli_common.parse_run_id
resolve_run_dir = _cli_common.resolve_run_dir
resolve_runs_root = _cli_common.resolve_runs_root
build_run_slug = _cli_common.build_run_slug
slugify_run_component = _cli_common.slugify_run_component
write_json = _cli_common.write_json
RawTrendingSnapshot = models.RawTrendingSnapshot
TrendingSnapshot = models.TrendingSnapshot
StaticGitHubTrendingProvider = provider.StaticGitHubTrendingProvider
annotate_snapshot_diff = tools.annotate_snapshot_diff
get_current_github_snapshot = tools.get_current_github_snapshot
get_github_archive_snapshot = tools.get_github_archive_snapshot
_normalize_github_snapshot = github_trending._normalize_github_snapshot


class FetchError(RuntimeError):
    pass


def _default_snapshot_date() -> str:
    return date.today().isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch the current GitHub trending snapshot, diff against the previous run, and write a single snapshot.json artifact."
    )
    parser.add_argument("--snapshot-date", default=_default_snapshot_date())
    parser.add_argument("--since", required=True, choices=["daily", "weekly", "monthly"])
    parser.add_argument("--language", default="all")
    parser.add_argument("--source", default="github-trending")
    parser.add_argument("--bootstrap-history", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--allow-empty-history",
        action="store_true",
        default=False,
        help=(
            "Proceed without a previous snapshot when none can be located "
            "(no prior run, no archive entry). Marks every current entry as new "
            "and sets history_source='first_run'. Use only for genuine first-run "
            "or bootstrap scenarios — does not mask network/auth failures."
        ),
    )
    parser.add_argument("--artifact-root")
    parser.add_argument("--current-snapshot-json")
    parser.add_argument("--previous-snapshot-json")
    parser.add_argument("--archive-snapshot-json")
    parser.add_argument("--run-dir")
    parser.add_argument("--output-path")
    parser.add_argument(
        "--supplemental", action="store_true",
        help="Write snapshot.<language>.json and use the same file from earlier runs of the main chart.",
    )
    parser.add_argument(
        "--print-only",
        action="store_true",
        default=False,
        help=(
            "Print the snapshot JSON to stdout without persisting it. "
            "Required when neither --run-dir nor --output-path is given; "
            "otherwise the script refuses to run to avoid silently dropping "
            "the snapshot."
        ),
    )
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args()


def _load_current_snapshot(args: argparse.Namespace) -> TrendingSnapshot:
    try:
        data = load_json(args.current_snapshot_json)
        if data is None:
            return get_current_github_snapshot(
                snapshot_date=args.snapshot_date,
                since=args.since,
                language=args.language,
            )
        static = StaticGitHubTrendingProvider(snapshot=RawTrendingSnapshot.from_dict(data))
        return get_current_github_snapshot(
            snapshot_date=args.snapshot_date,
            since=args.since,
            language=args.language,
            provider=static,
        )
    except Exception as exc:
        raise FetchError(f"current snapshot fetch failed: {exc}") from exc


def _load_previous_snapshot_payload(payload: dict) -> TrendingSnapshot:
    snapshot_payload = payload.get("snapshot", payload)
    return TrendingSnapshot.from_dict(snapshot_payload)


def _validate_previous(snapshot: TrendingSnapshot, *, args: argparse.Namespace, origin: str) -> TrendingSnapshot:
    if snapshot.snapshot_date >= args.snapshot_date:
        raise FetchError(
            f"previous snapshot from {origin} must be older than {args.snapshot_date}, got {snapshot.snapshot_date}"
        )
    if snapshot.since != args.since or snapshot.language != args.language or snapshot.source != args.source:
        raise FetchError(
            f"previous snapshot from {origin} mismatches source/since/language: "
            f"expected {args.source}/{args.since}/{args.language}, got {snapshot.source}/{snapshot.since}/{snapshot.language}"
        )
    return snapshot


def _find_previous_run_snapshot(
    args: argparse.Namespace, run_dir: Path | None, *, run_slug: str, snapshot_name: str,
) -> TrendingSnapshot | None:
    runs_root = resolve_runs_root(run_dir=run_dir, artifact_root=args.artifact_root)
    if not runs_root.is_dir():
        return None
    current_resolved = run_dir.resolve() if run_dir is not None else None
    for candidate in sorted(runs_root.iterdir(), reverse=True):
        if not candidate.is_dir():
            continue
        if current_resolved is not None and candidate.resolve() == current_resolved:
            continue
        try:
            parsed = parse_run_id(candidate.name)
        except ValueError:
            continue
        if parsed["run_slug"] != run_slug or parsed["snapshot_date"] >= args.snapshot_date:
            continue
        snapshot_path = candidate / snapshot_name
        if not snapshot_path.is_file():
            continue
        payload = load_json(str(snapshot_path))
        if payload is None:
            continue
        snapshot = _load_previous_snapshot_payload(payload)
        return _validate_previous(snapshot, args=args, origin=str(snapshot_path))
    return None


def _load_previous(
    args: argparse.Namespace, run_dir: Path | None, *, run_slug: str, snapshot_name: str,
) -> tuple[TrendingSnapshot | None, str]:
    if args.previous_snapshot_json:
        try:
            data = load_json(args.previous_snapshot_json)
        except Exception as exc:
            raise FetchError(f"previous snapshot load failed: {exc}") from exc
        if data is not None:
            snapshot = _load_previous_snapshot_payload(data)
            return _validate_previous(snapshot, args=args, origin=args.previous_snapshot_json), "previous_snapshot_override"

    previous = _find_previous_run_snapshot(args, run_dir, run_slug=run_slug, snapshot_name=snapshot_name)
    if previous is not None:
        return previous, "previous_run"

    if not args.bootstrap_history:
        if args.allow_empty_history:
            return None, "first_run"
        raise FetchError(
            "previous snapshot is required for diff, but no previous run snapshot was available and archive bootstrap is disabled"
        )

    try:
        archive_data = load_json(args.archive_snapshot_json)
        if archive_data is not None:
            raw_archive = RawTrendingSnapshot.from_dict(archive_data)
        else:
            raw_archive = get_github_archive_snapshot(
                snapshot_date=args.snapshot_date,
                since=args.since,
                language=args.language,
            )
    except Exception as exc:
        raise FetchError(f"archive snapshot fetch failed: {exc}") from exc

    if raw_archive is None:
        if args.allow_empty_history:
            return None, "first_run"
        raise FetchError(
            "archive snapshot fetch failed: no historical snapshot was found for the requested date/since/language"
        )

    try:
        archive_snapshot = _normalize_github_snapshot(
            raw_archive,
            snapshot_date=args.snapshot_date,
            since=args.since,
            language=args.language,
            source=f"{args.source}-archive",
        )
    except Exception as exc:
        raise FetchError(f"archive snapshot normalization failed: {exc}") from exc
    return archive_snapshot, "archive_bootstrap"


def main() -> int:
    try:
        args = parse_args()
        run_dir = resolve_run_dir(args.run_dir)

        if args.output_path is None and run_dir is None and not args.print_only:
            raise FetchError(
                "no output destination: pass --run-dir <dir>, --output-path <file>, "
                "or --print-only. The DEEPTREND_RUN_DIR env var is also accepted but "
                "is not inherited across separate bash invocations — prefer --run-dir."
            )

        run_slug = build_run_slug(source=args.source, since=args.since, language=args.language)
        snapshot_name = "snapshot.json"
        if args.supplemental:
            if run_dir is None or args.output_path is not None:
                raise FetchError("--supplemental requires a run directory and its standard snapshot filename")
            try:
                parent_run = parse_run_id(run_dir.name)
            except ValueError as exc:
                raise FetchError(f"invalid supplemental run directory: {exc}") from exc
            if parent_run["snapshot_date"] != args.snapshot_date:
                raise FetchError("supplemental snapshot date must match the parent run date")
            run_slug = parent_run["run_slug"]
            language_slug = slugify_run_component(args.language, fallback="all")
            snapshot_name = f"snapshot.{language_slug}.json"

        current = _load_current_snapshot(args)
        previous, history_source = _load_previous(args, run_dir, run_slug=run_slug, snapshot_name=snapshot_name)
        annotated = annotate_snapshot_diff(current, previous, history_source=history_source)

        payload = annotated.to_dict()

        output_path = args.output_path
        if output_path is None and run_dir is not None:
            output_path = str(run_dir / snapshot_name)
        if output_path:
            write_json(output_path, payload, pretty=args.pretty)
        print(dump_json(payload, pretty=args.pretty))
        return 0
    except FetchError as exc:
        print(f"fetch_snapshot failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
