from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ...config import settings
from ...models import RawRepoFileContent, RawTrendingEntry, RawTrendingSnapshot
from ..git import GitRepoProvider


def _normalize_key(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _archive_language_label(language: str) -> str:
    mapping = {
        "all": "All languages",
        "c#": "C#",
        "c++": "C++",
        "hcl": "HCL",
        "javascript": "JavaScript",
        "makefile": "Makefile",
        "python": "Python",
        "shell": "Shell",
        "typescript": "TypeScript",
        "webassembly": "WebAssembly",
    }
    normalized = language.strip().lower()
    if normalized in mapping:
        return mapping[normalized]
    return language[:1].upper() + language[1:] if language else ""


def _looks_like_repo_item(item: dict[str, Any]) -> bool:
    return bool(
        item.get("full_name")
        or item.get("repo_full_name")
        or item.get("repository")
        or item.get("name")
        or item.get("title")
        or item.get("url")
    )


def _extract_archive_repo_full_name(item: dict[str, Any]) -> str:
    for key in ("full_name", "repo_full_name", "repository", "name", "title"):
        value = str(item.get(key) or "").strip().strip("/")
        if value.count("/") == 1:
            return value
    url = str(item.get("url") or "").strip()
    if "github.com/" not in url:
        return ""
    return url.split("github.com/", 1)[1].strip("/").split("?", 1)[0].split("#", 1)[0]


def _filter_archive_entries(items: list[Any], *, language: str) -> list[dict[str, Any]]:
    expected_language = _normalize_key(language)
    all_languages = _normalize_key("all")
    entries: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict) or not _looks_like_repo_item(item):
            continue
        item_language = _normalize_key(
            str(item.get("language") or item.get("lang") or item.get("programming_language") or "")
        )
        if expected_language not in {"", all_languages} and item_language and item_language != expected_language:
            continue
        entries.append(item)
    return entries


def _extract_archive_language_entries(payload: Any, *, language: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return _filter_archive_entries(payload, language=language)
    if not isinstance(payload, dict):
        return []

    normalized_lookup = {_normalize_key(key): value for key, value in payload.items()}
    for key in [language, _archive_language_label(language), "all", "All languages", "all languages"]:
        nested = normalized_lookup.get(_normalize_key(key))
        if nested is None:
            continue
        extracted = _extract_archive_language_entries(nested, language=language)
        if extracted:
            return extracted

    for key in ("repositories", "repository", "items", "data", "languages"):
        nested = normalized_lookup.get(_normalize_key(key))
        if nested is None:
            continue
        extracted = _extract_archive_language_entries(nested, language=language)
        if extracted:
            return extracted

    if _looks_like_repo_item(payload):
        return [payload]
    return []


def _load_archive_payload(raw_file: RawRepoFileContent) -> Any | None:
    content = raw_file.content
    if not isinstance(content, str) or not content.strip():
        return None
    return json.loads(content)


@dataclass
class GitHubTrendingArchiveProvider:
    base_url: str = settings.github_base_url
    archive_repo_full_name: str = settings.github_trending_archive_repo_full_name
    archive_ref: str = settings.github_trending_archive_ref
    archive_path_root: str = "archive/repository"
    git_provider: GitRepoProvider = field(default_factory=GitRepoProvider, repr=False)

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        self.archive_repo_full_name = self.archive_repo_full_name.strip().strip("/")
        self.archive_ref = self.archive_ref.strip() or "main"
        self.archive_path_root = self.archive_path_root.strip().strip("/")

    def fetch_archive_snapshot(
        self,
        *,
        snapshot_date: str,
        since: str,
        language: str,
    ) -> RawTrendingSnapshot | None:
        if since != "daily":
            return None

        payload, source_url = self._fetch_archive_payload(snapshot_date=snapshot_date)
        if payload is None:
            return None

        entries = _extract_archive_language_entries(payload, language=language)
        normalized_entries: list[RawTrendingEntry] = []
        for rank, item in enumerate(entries[:25], start=1):
            repo_full_name = _extract_archive_repo_full_name(item)
            if not repo_full_name:
                continue
            normalized_entries.append(
                RawTrendingEntry(
                    rank=rank,
                    repo_full_name=repo_full_name,
                    repo_url=str(item.get("url") or f"{self.base_url}/{repo_full_name}"),
                )
            )
        return RawTrendingSnapshot(entries=normalized_entries, source_url=source_url)

    def _fetch_archive_payload(self, *, snapshot_date: str) -> tuple[object, str | None]:
        year = snapshot_date[:4]
        archive_path = f"{self.archive_path_root}/{year}/{snapshot_date}.json"
        raw_file = self.git_provider.fetch_file_content(
            self.archive_repo_full_name,
            archive_path,
            ref=self.archive_ref,
        )
        payload = _load_archive_payload(raw_file)
        if payload is None:
            return None, None
        source_url = (
            f"{self.base_url}/{self.archive_repo_full_name}/blob/{self.archive_ref}/{archive_path}"
        )
        return payload, source_url


@dataclass
class StaticGitHubTrendingArchiveProvider:
    snapshots: dict[tuple[str, str, str], RawTrendingSnapshot] = field(default_factory=dict)

    def fetch_archive_snapshot(
        self,
        *,
        snapshot_date: str,
        since: str,
        language: str,
    ) -> RawTrendingSnapshot | None:
        return self.snapshots.get((snapshot_date, since, language))
