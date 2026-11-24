from __future__ import annotations

from ...models import RawTrendingSnapshot, TrendingEntry, TrendingSnapshot, utcnow_iso
from ...provider import GitHubTrendingProvider


def get_current_github_snapshot(
    snapshot_date: str,
    since: str,
    language: str,
    *,
    provider: GitHubTrendingProvider | None = None,
) -> TrendingSnapshot:
    raw_snapshot = (provider or GitHubTrendingProvider()).fetch_current_snapshot(
        snapshot_date=snapshot_date,
        since=since,
        language=language,
    )
    return _normalize_github_snapshot(
        raw_snapshot,
        snapshot_date=snapshot_date,
        since=since,
        language=language,
    )


def _normalize_github_snapshot(
    raw_snapshot: RawTrendingSnapshot,
    snapshot_date: str,
    since: str,
    language: str,
    *,
    source: str = "github-trending",
    fetched_at: str | None = None,
) -> TrendingSnapshot:
    normalized_entries: list[TrendingEntry] = []
    for index, entry in enumerate(raw_snapshot.entries, start=1):
        repo_full_name = entry.repo_full_name.strip().strip("/")
        if not repo_full_name:
            continue
        normalized_entries.append(
            TrendingEntry(
                rank=entry.rank if entry.rank is not None else index,
                repo_full_name=repo_full_name,
                repo_url=entry.repo_url or f"https://github.com/{repo_full_name}",
                stars_period=entry.stars_period or 0,
            )
        )

    return TrendingSnapshot(
        snapshot_date=snapshot_date,
        since=since,
        language=language,
        source=source,
        entries=normalized_entries,
        source_url=raw_snapshot.source_url,
        fetched_at=fetched_at or utcnow_iso(),
    )
