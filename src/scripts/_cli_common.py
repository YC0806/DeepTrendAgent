from __future__ import annotations

import json
import os
import re
from datetime import date
from pathlib import Path
from typing import Any

from ..config import settings


DEEPTREND_RUN_DIR_ENV = "DEEPTREND_RUN_DIR"
DEEPTREND_RUN_ID_ENV = "DEEPTREND_RUN_ID"
DEEPTREND_RUN_SLUG_ENV = "DEEPTREND_RUN_SLUG"
_RUN_SLUG_RE = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
_RUN_ID_RE = re.compile(r"^(?P<snapshot_date>\d{4}-\d{2}-\d{2})__(?P<run_slug>[a-z0-9]+(?:[-_][a-z0-9]+)*)$")
REPO_SUBDIR = "repo"


def load_json(path: str | None) -> Any:
    if path is None:
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def dump_json(payload: Any, *, pretty: bool) -> str:
    if pretty:
        return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def write_json(path: str | Path, payload: Any, *, pretty: bool) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(dump_json(payload, pretty=pretty), encoding="utf-8")
    return output_path


def repo_slug_from_full_name(repo_full_name: str) -> str:
    return repo_full_name.replace("/", "__")


def default_snapshot_date() -> str:
    return date.today().isoformat()


def validate_snapshot_date(snapshot_date: str) -> str:
    try:
        date.fromisoformat(snapshot_date)
    except ValueError as exc:
        raise ValueError(f"snapshot_date must be YYYY-MM-DD, got {snapshot_date!r}") from exc
    return snapshot_date


def validate_run_slug(slug: str) -> str:
    normalized = slug.strip()
    if normalized != slug or not normalized:
        raise ValueError("slug must be a non-empty filesystem-safe ASCII slug")
    if not _RUN_SLUG_RE.fullmatch(normalized):
        raise ValueError(
            "slug must match ^[a-z0-9]+(?:[-_][a-z0-9]+)*$ and use only lowercase ASCII letters, digits, '-' or '_'"
        )
    return normalized


def slugify_run_component(value: str, *, fallback: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        normalized = fallback
    normalized = normalized.replace("+", "-plus-").replace("#", "-sharp-")
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized)
    normalized = normalized.strip("-_")
    return normalized or fallback


def build_run_slug(*, source: str, since: str, language: str) -> str:
    return validate_run_slug(
        "-".join(
            (
                slugify_run_component(source, fallback="source"),
                slugify_run_component(since, fallback="daily"),
                slugify_run_component(language, fallback="all"),
            )
        )
    )


def resolve_artifact_root(artifact_root: str | None = None) -> Path:
    root = Path(artifact_root or settings.deeptrend_artifact_root).expanduser()
    return root.resolve()


def build_run_id(snapshot_date: str, *, source: str, since: str, language: str) -> str:
    return f"{validate_snapshot_date(snapshot_date)}__{build_run_slug(source=source, since=since, language=language)}"


def parse_run_id(run_id: str) -> dict[str, str]:
    match = _RUN_ID_RE.fullmatch(run_id)
    if not match:
        raise ValueError(f"run_id must match <YYYY-MM-DD>__<run_slug>, got {run_id!r}")
    parsed = match.groupdict()
    validate_snapshot_date(parsed["snapshot_date"])
    validate_run_slug(parsed["run_slug"])
    return parsed


def init_run_layout(
    *,
    snapshot_date: str,
    source: str,
    since: str,
    language: str,
    artifact_root: str | None = None,
) -> dict[str, Any]:
    validated_snapshot_date = validate_snapshot_date(snapshot_date)
    run_slug = build_run_slug(source=source, since=since, language=language)
    run_id = build_run_id(validated_snapshot_date, source=source, since=since, language=language)
    artifact_root_path = resolve_artifact_root(artifact_root)
    runs_root = artifact_root_path / "runs"
    run_dir = runs_root / run_id

    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / REPO_SUBDIR).mkdir(parents=True, exist_ok=True)

    return {
        "artifact_root": str(artifact_root_path),
        "environment": {
            DEEPTREND_RUN_DIR_ENV: str(run_dir),
            DEEPTREND_RUN_ID_ENV: run_id,
            DEEPTREND_RUN_SLUG_ENV: run_slug,
        },
        "language": language,
        "run_dir": str(run_dir),
        "run_id": run_id,
        "run_slug": run_slug,
        "runs_root": str(runs_root),
        "since": since,
        "snapshot_date": validated_snapshot_date,
        "source": source,
    }


def resolve_run_dir(run_dir: str | None = None) -> Path | None:
    candidate = run_dir or os.environ.get(DEEPTREND_RUN_DIR_ENV)
    if not candidate:
        return None
    return Path(candidate).expanduser().resolve()


def resolve_runs_root(*, run_dir: str | Path | None = None, artifact_root: str | None = None) -> Path:
    if run_dir is not None:
        return Path(run_dir).expanduser().resolve().parent
    return resolve_artifact_root(artifact_root) / "runs"
