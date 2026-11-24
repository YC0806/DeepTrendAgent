from __future__ import annotations

from collections.abc import Iterable

from ...models import SupplementalCandidate, TrendingEntry, TrendingSnapshot


def annotate_snapshot_diff(
    current_snapshot: TrendingSnapshot,
    previous_snapshot: TrendingSnapshot | None,
    *,
    history_source: str | None = None,
) -> TrendingSnapshot:
    """Annotate entries with their previous rank and period stars when available."""

    previous_entries = (
        {entry.repo_full_name.casefold(): entry for entry in previous_snapshot.entries}
        if previous_snapshot is not None
        else {}
    )

    annotated_entries: list[TrendingEntry] = []
    for entry in current_snapshot.entries:
        previous = previous_entries.get(entry.repo_full_name.casefold())
        annotated_entries.append(
            TrendingEntry(
                rank=entry.rank,
                repo_full_name=entry.repo_full_name,
                repo_url=entry.repo_url,
                stars_period=entry.stars_period,
                is_new=previous is None,
                previous_rank=previous.rank if previous is not None else None,
                # Existing snapshots also use zero for unavailable period stars.
                previous_stars_period=(previous.stars_period or None) if previous is not None else None,
            )
        )

    return TrendingSnapshot(
        snapshot_date=current_snapshot.snapshot_date,
        since=current_snapshot.since,
        language=current_snapshot.language,
        source=current_snapshot.source,
        entries=annotated_entries,
        source_url=current_snapshot.source_url,
        previous_snapshot_date=previous_snapshot.snapshot_date if previous_snapshot is not None else None,
        history_source=history_source,
        fetched_at=current_snapshot.fetched_at,
    )


def merge_new_entries(
    primary: TrendingSnapshot, supplements: Iterable[TrendingSnapshot],
) -> list[SupplementalCandidate]:
    """Merge new entries from the given charts in order, excluding primary entries."""
    seen = {entry.repo_full_name.casefold() for entry in primary.entries}
    candidates = []
    for snapshot in supplements:
        for entry in snapshot.entries:
            key = entry.repo_full_name.casefold()
            if not entry.is_new or key in seen:
                continue
            seen.add(key)
            candidates.append(SupplementalCandidate(
                repo_full_name=entry.repo_full_name,
                language=snapshot.language,
                rank=entry.rank,
                stars_period=entry.stars_period,
            ))
    return candidates
