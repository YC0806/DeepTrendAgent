from __future__ import annotations

from typing import Protocol

from ...models import (
    RawCommitInfo,
    RawRepoMetadata,
    RawRepoRelease,
    RawRepoResources,
    RawRepoTag,
    RepoContext,
)
from ...provider import GitHubRepoResourcesProvider


class GitHubRepoProviderLike(Protocol):
    def fetch_repo_resources(self, repo_full_name: str) -> RawRepoResources: ...

    def fetch_repo_metadata(self, repo_full_name: str) -> RawRepoMetadata: ...

    def fetch_default_branch(self, repo_full_name: str) -> str: ...

    def fetch_repo_readme(
        self,
        repo_full_name: str,
        *,
        ref: str | None = None,
    ) -> str | None: ...

    def fetch_repo_releases(
        self,
        repo_full_name: str,
        *,
        limit: int = 3,
    ) -> list[RawRepoRelease]: ...

    def fetch_repo_tags(
        self,
        repo_full_name: str,
        *,
        limit: int = 20,
    ) -> list[RawRepoTag]: ...

    def fetch_last_commit(
        self,
        repo_full_name: str,
        *,
        ref: str | None = None,
    ) -> RawCommitInfo: ...


def get_github_repo_resources(
    repo_full_name: str,
    *,
    provider: GitHubRepoProviderLike | None = None,
) -> RawRepoResources:
    return (provider or GitHubRepoResourcesProvider()).fetch_repo_resources(repo_full_name)


def get_github_repo_metadata(
    repo_full_name: str,
    *,
    provider: GitHubRepoProviderLike | None = None,
) -> RawRepoMetadata:
    return (provider or GitHubRepoResourcesProvider()).fetch_repo_metadata(repo_full_name)


def get_github_repo_default_branch(
    repo_full_name: str,
    *,
    provider: GitHubRepoProviderLike | None = None,
) -> str:
    return (provider or GitHubRepoResourcesProvider()).fetch_default_branch(repo_full_name)


def get_github_repo_readme(
    repo_full_name: str,
    *,
    ref: str | None = None,
    provider: GitHubRepoProviderLike | None = None,
) -> str | None:
    return (provider or GitHubRepoResourcesProvider()).fetch_repo_readme(repo_full_name, ref=ref)


def get_github_repo_releases(
    repo_full_name: str,
    *,
    limit: int = 3,
    provider: GitHubRepoProviderLike | None = None,
) -> list[RawRepoRelease]:
    return (provider or GitHubRepoResourcesProvider()).fetch_repo_releases(repo_full_name, limit=limit)


def get_github_repo_tags(
    repo_full_name: str,
    *,
    limit: int = 20,
    provider: GitHubRepoProviderLike | None = None,
) -> list[RawRepoTag]:
    return (provider or GitHubRepoResourcesProvider()).fetch_repo_tags(repo_full_name, limit=limit)


def get_github_repo_last_commit(
    repo_full_name: str,
    *,
    ref: str | None = None,
    provider: GitHubRepoProviderLike | None = None,
) -> RawCommitInfo:
    return (provider or GitHubRepoResourcesProvider()).fetch_last_commit(repo_full_name, ref=ref)


def build_github_repo_context(
    raw_resources: RawRepoResources | None = None,
    *,
    metadata: RawRepoMetadata | None = None,
    readme: str | None = None,
    releases: list[RawRepoRelease] | None = None,
    tags: list[RawRepoTag] | None = None,
    last_commit: RawCommitInfo | None = None,
) -> RepoContext:
    if raw_resources is not None:
        metadata = metadata or raw_resources.metadata
        readme = readme or raw_resources.readme
        releases = releases if releases is not None else list(raw_resources.releases)
        tags = tags if tags is not None else list(raw_resources.tags)
        last_commit = last_commit or raw_resources.last_commit
    if metadata is None:
        raise ValueError("metadata is required to build repo context")

    release_items = list(releases or [])
    tag_items = list(tags or [])
    latest_release = release_items[0] if release_items else None

    return RepoContext(
        repo_full_name=metadata.repo_full_name,
        repo_url=metadata.repo_url or f"https://github.com/{metadata.repo_full_name}",
        description=metadata.description,
        primary_language=metadata.primary_language,
        stars_total=metadata.stars_total,
        topics=list(metadata.topics),
        homepage_url=metadata.homepage_url,
        readme=readme,
        release_notes=_format_release_notes(release_items),
        latest_release_title=latest_release.title if latest_release is not None else None,
        latest_release_published_at=latest_release.published_at if latest_release is not None else None,
        tag_names=[tag.name for tag in tag_items],
        last_commit_hash=last_commit.sha if last_commit is not None else None,
        last_commit_at=last_commit.committed_at if last_commit is not None else None,
    )


def _format_release_notes(releases: list[RawRepoRelease]) -> str | None:
    parts: list[str] = []
    for release in releases:
        label = release.title or "Untitled release"
        if release.published_at:
            label = f"{label} ({release.published_at})"
        if release.notes:
            parts.append(f"{label}: {release.notes}")
        else:
            parts.append(label)
    if not parts:
        return None
    return "\n\n".join(parts)
