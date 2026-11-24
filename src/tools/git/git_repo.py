from __future__ import annotations

from typing import Protocol

from ...models import RawCommitInfo, RawRepoFileContent, RawRepoTreeEntry
from ...provider import GitRepoProvider


class GitRepoProviderLike(Protocol):
    def fetch_file_content(
        self,
        repo_full_name: str,
        path: str,
        *,
        ref: str | None = None,
    ) -> RawRepoFileContent: ...

    def fetch_tree(
        self,
        repo_full_name: str,
        *,
        path: str = "",
        ref: str | None = None,
    ) -> list[RawRepoTreeEntry]: ...

    def fetch_commit_history(
        self,
        repo_full_name: str,
        *,
        path: str | None = None,
        ref: str | None = None,
        limit: int = 20,
    ) -> list[RawCommitInfo]: ...

    def fetch_last_commit_for_path(
        self,
        repo_full_name: str,
        path: str,
        *,
        ref: str | None = None,
    ) -> RawCommitInfo: ...

    def fetch_diff(
        self,
        repo_full_name: str,
        *,
        base_ref: str,
        head_ref: str,
        path: str | None = None,
    ) -> str: ...


def get_git_repo_file_content(
    repo_full_name: str,
    path: str,
    *,
    ref: str | None = None,
    provider: GitRepoProviderLike | None = None,
) -> RawRepoFileContent:
    return (provider or GitRepoProvider()).fetch_file_content(repo_full_name, path, ref=ref)


def get_git_repo_tree(
    repo_full_name: str,
    *,
    path: str = "",
    ref: str | None = None,
    provider: GitRepoProviderLike | None = None,
) -> list[RawRepoTreeEntry]:
    return (provider or GitRepoProvider()).fetch_tree(repo_full_name, path=path, ref=ref)


def get_git_repo_commit_history(
    repo_full_name: str,
    *,
    path: str | None = None,
    ref: str | None = None,
    limit: int = 20,
    provider: GitRepoProviderLike | None = None,
) -> list[RawCommitInfo]:
    return (provider or GitRepoProvider()).fetch_commit_history(repo_full_name, path=path, ref=ref, limit=limit)


def get_git_repo_last_commit_for_path(
    repo_full_name: str,
    path: str,
    *,
    ref: str | None = None,
    provider: GitRepoProviderLike | None = None,
) -> RawCommitInfo:
    return (provider or GitRepoProvider()).fetch_last_commit_for_path(repo_full_name, path, ref=ref)


def get_git_repo_diff(
    repo_full_name: str,
    *,
    base_ref: str,
    head_ref: str,
    path: str | None = None,
    provider: GitRepoProviderLike | None = None,
) -> str:
    return (provider or GitRepoProvider()).fetch_diff(
        repo_full_name,
        base_ref=base_ref,
        head_ref=head_ref,
        path=path,
    )
