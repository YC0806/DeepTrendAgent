from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from typing import Any


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _serialize(item) for key, item in asdict(value).items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


@dataclass
class Serializable:
    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


# ---------------------------------------------------------------------------
# Raw inputs from external sources (provider layer)
# ---------------------------------------------------------------------------


@dataclass
class RawTrendingEntry(Serializable):
    repo_full_name: str
    rank: int | None = None
    repo_url: str | None = None
    stars_period: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RawTrendingEntry":
        return cls(
            repo_full_name=data["repo_full_name"],
            rank=data.get("rank"),
            repo_url=data.get("repo_url"),
            stars_period=data.get("stars_period"),
        )


@dataclass
class RawTrendingSnapshot(Serializable):
    entries: list[RawTrendingEntry]
    source_url: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RawTrendingSnapshot":
        return cls(
            entries=[RawTrendingEntry.from_dict(item) for item in data.get("entries", [])],
            source_url=data.get("source_url"),
        )


@dataclass
class RawRepoMetadata(Serializable):
    repo_full_name: str
    repo_url: str | None = None
    description: str | None = None
    primary_language: str | None = None
    stars_total: int = 0
    topics: list[str] = field(default_factory=list)
    homepage_url: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RawRepoMetadata":
        return cls(
            repo_full_name=data["repo_full_name"],
            repo_url=data.get("repo_url"),
            description=data.get("description"),
            primary_language=data.get("primary_language"),
            stars_total=data.get("stars_total", 0),
            topics=list(data.get("topics", [])),
            homepage_url=data.get("homepage_url"),
        )




@dataclass
class RawRepoRelease(Serializable):
    title: str | None = None
    notes: str | None = None
    published_at: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RawRepoRelease":
        return cls(
            title=data.get("title"),
            notes=data.get("notes"),
            published_at=data.get("published_at"),
        )


@dataclass
class RawRepoTag(Serializable):
    name: str
    commit_sha: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RawRepoTag":
        return cls(
            name=data["name"],
            commit_sha=data.get("commit_sha"),
        )


@dataclass
class RawCommitInfo(Serializable):
    sha: str | None = None
    committed_at: str | None = None
    message: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RawCommitInfo":
        return cls(
            sha=data.get("sha"),
            committed_at=data.get("committed_at"),
            message=data.get("message"),
        )


@dataclass
class RawRepoFileContent(Serializable):
    path: str
    ref: str | None = None
    content: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RawRepoFileContent":
        return cls(
            path=data["path"],
            ref=data.get("ref"),
            content=data.get("content"),
        )


@dataclass
class RawRepoTreeEntry(Serializable):
    path: str
    entry_type: str
    ref: str | None = None
    sha: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RawRepoTreeEntry":
        return cls(
            path=data["path"],
            entry_type=data["entry_type"],
            ref=data.get("ref"),
            sha=data.get("sha"),
        )


@dataclass
class RawRepoResources(Serializable):
    metadata: RawRepoMetadata
    default_branch: str | None = None
    readme: str | None = None
    releases: list[RawRepoRelease] = field(default_factory=list)
    tags: list[RawRepoTag] = field(default_factory=list)
    last_commit: RawCommitInfo = field(default_factory=RawCommitInfo)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RawRepoResources":
        _readme = data.get("readme")
        if isinstance(_readme, str):
            readme = _readme
        elif isinstance(_readme, dict):
            readme = _readme.get("content")
        else:
            readme = None
        return cls(
            metadata=RawRepoMetadata.from_dict(data["metadata"]),
            default_branch=data.get("default_branch"),
            readme=readme,
            releases=[RawRepoRelease.from_dict(item) for item in data.get("releases", [])],
            tags=[RawRepoTag.from_dict(item) for item in data.get("tags", [])],
            last_commit=RawCommitInfo.from_dict(data.get("last_commit", {})),
        )


# ---------------------------------------------------------------------------
# Core business models
# ---------------------------------------------------------------------------


@dataclass
class TrendingEntry(Serializable):
    rank: int
    repo_full_name: str
    repo_url: str
    stars_period: int = 0
    is_new: bool = False
    previous_rank: int | None = None
    previous_stars_period: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TrendingEntry":
        return cls(
            rank=data["rank"],
            repo_full_name=data["repo_full_name"],
            repo_url=data["repo_url"],
            stars_period=data.get("stars_period", 0),
            is_new=data.get("is_new", False),
            previous_rank=data.get("previous_rank"),
            previous_stars_period=data.get("previous_stars_period"),
        )


@dataclass
class TrendingSnapshot(Serializable):
    snapshot_date: str
    since: str
    language: str
    source: str
    entries: list[TrendingEntry]
    source_url: str | None = None
    previous_snapshot_date: str | None = None
    history_source: str | None = None
    fetched_at: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TrendingSnapshot":
        return cls(
            snapshot_date=data["snapshot_date"],
            since=data["since"],
            language=data["language"],
            source=data["source"],
            entries=[TrendingEntry.from_dict(item) for item in data.get("entries", [])],
            source_url=data.get("source_url"),
            previous_snapshot_date=data.get("previous_snapshot_date"),
            history_source=data.get("history_source"),
            fetched_at=data.get("fetched_at", ""),
        )


@dataclass
class SupplementalCandidate(Serializable):
    repo_full_name: str
    language: str
    rank: int
    stars_period: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SupplementalCandidate":
        return cls(
            repo_full_name=data["repo_full_name"],
            language=data["language"],
            rank=data["rank"],
            stars_period=data["stars_period"],
        )


@dataclass
class RepoContext(Serializable):
    repo_full_name: str
    repo_url: str
    description: str | None = None
    primary_language: str | None = None
    stars_total: int = 0
    topics: list[str] = field(default_factory=list)
    homepage_url: str | None = None
    readme: str | None = None
    release_notes: str | None = None
    latest_release_title: str | None = None
    latest_release_published_at: str | None = None
    tag_names: list[str] = field(default_factory=list)
    last_commit_hash: str | None = None
    last_commit_at: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RepoContext":
        return cls(
            repo_full_name=data["repo_full_name"],
            repo_url=data["repo_url"],
            description=data.get("description"),
            primary_language=data.get("primary_language"),
            stars_total=data.get("stars_total", 0),
            topics=list(data.get("topics", [])),
            homepage_url=data.get("homepage_url"),
            readme=data.get("readme"),
            release_notes=data.get("release_notes"),
            latest_release_title=data.get("latest_release_title"),
            latest_release_published_at=data.get("latest_release_published_at"),
            tag_names=list(data.get("tag_names", [])),
            last_commit_hash=data.get("last_commit_hash"),
            last_commit_at=data.get("last_commit_at"),
        )


@dataclass
class RepoAnalysis(Serializable):
    repo_full_name: str
    disposition: str  # "tracked" | "adopt" | "skip"
    relevance: str    # "relevant" | "adjacent" | "irrelevant"
    summary: str
    why: str
    analysis_md: str | None = None
    error: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RepoAnalysis":
        return cls(
            repo_full_name=data["repo_full_name"],
            disposition=data["disposition"],
            relevance=data["relevance"],
            summary=data["summary"],
            why=data["why"],
            analysis_md=data.get("analysis_md"),
            error=data.get("error"),
        )


@dataclass
class TrendReport(Serializable):
    generated_at: str
    summary: str
    markdown: str
    statistics: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TrendReport":
        return cls(
            generated_at=data["generated_at"],
            summary=data["summary"],
            markdown=data["markdown"],
            statistics=dict(data.get("statistics", {})),
        )


@dataclass
class Delivery(Serializable):
    channel: str
    status: str  # "success" | "failed" | "skipped"
    summary: str = ""
    sent_at: str | None = None
    error: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Delivery":
        return cls(
            channel=data["channel"],
            status=data["status"],
            summary=data.get("summary", ""),
            sent_at=data.get("sent_at"),
            error=data.get("error"),
        )


@dataclass
class TrendRun(Serializable):
    run_id: str
    run_dir: str
    snapshot: TrendingSnapshot
    analyses: list[RepoAnalysis]
    report: TrendReport
    delivery: Delivery | None = None
    supplemental_candidates: list[SupplementalCandidate] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TrendRun":
        return cls(
            run_id=data["run_id"],
            run_dir=data["run_dir"],
            snapshot=TrendingSnapshot.from_dict(data["snapshot"]),
            analyses=[RepoAnalysis.from_dict(item) for item in data.get("analyses", [])],
            report=TrendReport.from_dict(data["report"]),
            delivery=Delivery.from_dict(data["delivery"]) if data.get("delivery") else None,
            supplemental_candidates=[
                SupplementalCandidate.from_dict(item) for item in data.get("supplemental_candidates", [])
            ],
        )
