from __future__ import annotations

from ...models import RawTrendingSnapshot
from ...provider import GitHubTrendingArchiveProvider


def get_github_archive_snapshot(
    snapshot_date: str,
    since: str,
    language: str,
    *,
    provider: GitHubTrendingArchiveProvider | None = None,
) -> RawTrendingSnapshot | None:
    return (provider or GitHubTrendingArchiveProvider()).fetch_archive_snapshot(
        snapshot_date=snapshot_date,
        since=since,
        language=language,
    )
