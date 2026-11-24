from __future__ import annotations

from pathlib import Path


WECOM_DIGEST_CHAR_LIMIT = 2048


def ensure_path_within_run_dir(path: Path, run_dir: Path) -> Path:
    resolved_path = path.expanduser().resolve()
    resolved_run_dir = run_dir.expanduser().resolve()
    try:
        resolved_path.relative_to(resolved_run_dir)
    except ValueError as exc:
        raise ValueError(f"path must stay inside run_dir: {resolved_path}") from exc
    return resolved_path


def report_attachment_filename(run_dir: Path) -> str:
    run_name = run_dir.expanduser().resolve().name
    if not run_name:
        raise ValueError(f"run_dir must have a basename: {run_dir}")
    return f"{run_name}.md"
