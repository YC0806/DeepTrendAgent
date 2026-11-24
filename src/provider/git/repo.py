from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ...config import settings
from ...models import RawCommitInfo, RawRepoFileContent, RawRepoTreeEntry


def _repo_slug(repo_full_name: str) -> str:
    parts = [part for part in repo_full_name.strip("/").split("/") if part]
    if len(parts) != 2:
        raise ValueError("repo_full_name must be owner/repo")
    return "__".join(parts)


@dataclass
class GitRepoProvider:
    git_bin: str = settings.git_bin
    cache_root: str = settings.deeptrend_git_cache_root
    remote_base_url: str = settings.github_base_url
    timeout: int = 60
    repo_paths: dict[str, str] = field(default_factory=dict)

    def fetch_file_content(
        self,
        repo_full_name: str,
        path: str,
        *,
        ref: str | None = None,
    ) -> RawRepoFileContent:
        object_ref = f"{ref or 'HEAD'}:{path}"
        content = self._run_git(repo_full_name, "show", object_ref, allow_not_found=True)
        return RawRepoFileContent(
            path=path,
            ref=ref,
            content=content,
        )

    def fetch_tree(
        self,
        repo_full_name: str,
        *,
        path: str = "",
        ref: str | None = None,
    ) -> list[RawRepoTreeEntry]:
        args = ["ls-tree", "-r", ref or "HEAD"]
        if path:
            args.extend(["--", path])
        raw_output = self._run_git(repo_full_name, *args)
        entries: list[RawRepoTreeEntry] = []
        for line in raw_output.splitlines():
            metadata, _, entry_path = line.partition("\t")
            if not metadata or not entry_path:
                continue
            parts = metadata.split()
            if len(parts) != 3:
                continue
            _mode, entry_type, sha = parts
            entries.append(
                RawRepoTreeEntry(
                    path=entry_path,
                    entry_type=entry_type,
                    ref=ref,
                    sha=sha,
                )
            )
        return entries

    def fetch_commit_history(
        self,
        repo_full_name: str,
        *,
        path: str | None = None,
        ref: str | None = None,
        limit: int = 20,
    ) -> list[RawCommitInfo]:
        args = [
            "log",
            "--format=%H%x1f%cI%x1f%s",
            f"-n{max(1, limit)}",
            ref or "HEAD",
        ]
        if path:
            args.extend(["--", path])
        raw_output = self._run_git(repo_full_name, *args, allow_not_found=True)
        commits: list[RawCommitInfo] = []
        for line in raw_output.splitlines():
            sha, _, remainder = line.partition("\x1f")
            committed_at, _, message = remainder.partition("\x1f")
            if not sha:
                continue
            commits.append(
                RawCommitInfo(
                    sha=sha or None,
                    committed_at=committed_at or None,
                    message=message or None,
                )
            )
        return commits

    def fetch_last_commit_for_path(
        self,
        repo_full_name: str,
        path: str,
        *,
        ref: str | None = None,
    ) -> RawCommitInfo:
        commits = self.fetch_commit_history(
            repo_full_name,
            path=path,
            ref=ref,
            limit=1,
        )
        return commits[0] if commits else RawCommitInfo()

    def fetch_diff(
        self,
        repo_full_name: str,
        *,
        base_ref: str,
        head_ref: str,
        path: str | None = None,
    ) -> str:
        args = ["diff", "--no-ext-diff", "--stat", f"{base_ref}..{head_ref}"]
        if path:
            args.extend(["--", path])
        return self._run_git(repo_full_name, *args, allow_not_found=True)

    def _resolve_repo_dir(self, repo_full_name: str) -> Path:
        mapped = self.repo_paths.get(repo_full_name)
        if mapped:
            repo_dir = Path(mapped).expanduser().resolve()
            if repo_dir.exists():
                return repo_dir

        cache_dir = Path(self.cache_root).expanduser().resolve() / _repo_slug(repo_full_name)
        if not (cache_dir / ".git").exists():
            cache_dir.parent.mkdir(parents=True, exist_ok=True)
            self._run_process(
                [
                    self.git_bin,
                    "clone",
                    "--filter=blob:none",
                    "--no-checkout",
                    self._remote_url(repo_full_name),
                    str(cache_dir),
                ]
            )
        else:
            self._run_process(
                [
                    self.git_bin,
                    "-C",
                    str(cache_dir),
                    "fetch",
                    "--tags",
                    "--force",
                    "origin",
                ]
            )
        return cache_dir

    def _remote_url(self, repo_full_name: str) -> str:
        return f"{self.remote_base_url.rstrip('/')}/{repo_full_name}.git"

    def _run_git(
        self,
        repo_full_name: str,
        *args: str,
        allow_not_found: bool = False,
    ) -> str:
        repo_dir = self._resolve_repo_dir(repo_full_name)
        try:
            return self._run_process([self.git_bin, "-C", str(repo_dir), *args])
        except RuntimeError as exc:
            message = str(exc)
            if allow_not_found and (
                "exists on disk" in message
                or "does not exist" in message
                or "unknown revision" in message
                or "invalid object name" in message
                or "pathspec" in message
                or "Path '" in message
            ):
                return ""
            raise

    def _run_process(self, cmd: list[str]) -> str:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=self.timeout,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "git command failed")
        return result.stdout


@dataclass
class StaticGitRepoProvider:
    file_contents: dict[tuple[str, str, str | None], RawRepoFileContent] = field(default_factory=dict)
    trees: dict[tuple[str, str, str | None], list[RawRepoTreeEntry]] = field(default_factory=dict)
    commit_histories: dict[tuple[str, str | None, str | None, int], list[RawCommitInfo]] = field(
        default_factory=dict
    )
    diffs: dict[tuple[str, str, str, str | None], str] = field(default_factory=dict)

    def fetch_file_content(
        self,
        repo_full_name: str,
        path: str,
        *,
        ref: str | None = None,
    ) -> RawRepoFileContent:
        return self.file_contents.get(
            (repo_full_name, path, ref),
            RawRepoFileContent(path=path, ref=ref),
        )

    def fetch_tree(
        self,
        repo_full_name: str,
        *,
        path: str = "",
        ref: str | None = None,
    ) -> list[RawRepoTreeEntry]:
        return list(self.trees.get((repo_full_name, path, ref), []))

    def fetch_commit_history(
        self,
        repo_full_name: str,
        *,
        path: str | None = None,
        ref: str | None = None,
        limit: int = 20,
    ) -> list[RawCommitInfo]:
        return list(self.commit_histories.get((repo_full_name, path, ref, limit), []))

    def fetch_last_commit_for_path(
        self,
        repo_full_name: str,
        path: str,
        *,
        ref: str | None = None,
    ) -> RawCommitInfo:
        history = self.fetch_commit_history(repo_full_name, path=path, ref=ref, limit=1)
        return history[0] if history else RawCommitInfo()

    def fetch_diff(
        self,
        repo_full_name: str,
        *,
        base_ref: str,
        head_ref: str,
        path: str | None = None,
    ) -> str:
        return self.diffs.get((repo_full_name, base_ref, head_ref, path), "")
