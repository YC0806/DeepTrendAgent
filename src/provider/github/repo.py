from __future__ import annotations

import base64
import json
import logging
import re
import time
from dataclasses import dataclass, field
from http.client import IncompleteRead
from html import unescape
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener, urlopen

from ...config import settings
from ...models import (
    RawCommitInfo,
    RawRepoMetadata,
    RawRepoRelease,
    RawRepoResources,
    RawRepoTag,
)

logger = logging.getLogger(__name__)

_JSON_ACCEPT = "application/vnd.github+json"
_DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; TrendObserver/0.1)"
_RETRYABLE_STATUS_CODES = {403, 404, 429, 500, 502, 503, 504}
_UNSET = object()


def _normalize_proxy_url(value: str | None) -> str:
    proxy_url = str(value or "").strip()
    if not proxy_url:
        return ""
    if "://" not in proxy_url:
        return f"http://{proxy_url}"
    return proxy_url


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _split_repo_full_name(repo_full_name: str) -> tuple[str, str]:
    parts = [part for part in repo_full_name.strip("/").split("/") if part]
    if len(parts) != 2:
        raise ValueError("repo_full_name must be owner/repo")
    return parts[0], parts[1]


def _clean_markdown_text(value: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", value)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"`{1,3}", "", text)
    text = re.sub(r"(^|\n)\s{0,3}#{1,6}\s*", r"\1", text)
    text = re.sub(r"(^|\n)\s*[-*+]\s+", r"\1", text)
    text = unescape(text)
    return " ".join(text.split())


def _truncate(text: str, limit: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 1)].rstrip() + "..."


def _extract_topics(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    names = payload.get("names")
    if not isinstance(names, list):
        return []
    return [name for name in (_optional_text(item) for item in names) if name]


def _extract_stars_total(payload: Any) -> int:
    if not isinstance(payload, dict):
        return 0
    value = payload.get("stargazers_count")
    return value if isinstance(value, int) else 0


def _extract_readme(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    content = str(payload.get("content") or "").strip()
    if not content:
        return None
    try:
        raw = base64.b64decode(content.encode("utf-8"), validate=False)
    except (ValueError, TypeError) as exc:
        logger.warning("Failed to decode GitHub README content: %s", exc)
        return None
    cleaned = _clean_markdown_text(raw.decode("utf-8", errors="ignore"))
    return cleaned or None


def _extract_releases(payload: Any) -> list[RawRepoRelease]:
    if not isinstance(payload, list):
        return []
    releases: list[RawRepoRelease] = []
    for item in payload[:3]:
        if not isinstance(item, dict):
            continue
        notes = _clean_markdown_text(str(item.get("body") or ""))
        releases.append(
            RawRepoRelease(
                title=_optional_text(item.get("name") or item.get("tag_name")),
                notes=_optional_text(_truncate(notes, 300)),
                published_at=_optional_text(item.get("published_at")),
            )
        )
    return releases


def _extract_tags(payload: Any) -> list[RawRepoTag]:
    if not isinstance(payload, list):
        return []
    tags: list[RawRepoTag] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        commit = item.get("commit") if isinstance(item.get("commit"), dict) else {}
        name = _optional_text(item.get("name"))
        if not name:
            continue
        tags.append(
            RawRepoTag(
                name=name,
                commit_sha=_optional_text(commit.get("sha")),
            )
        )
    return tags


def _extract_last_commit(payload: Any) -> RawCommitInfo:
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        return RawCommitInfo()
    commit = payload[0]
    committed_at: str | None = None
    commit_block = commit.get("commit")
    if isinstance(commit_block, dict):
        committer = commit_block.get("committer")
        if isinstance(committer, dict):
            committed_at = _optional_text(committer.get("date"))
    return RawCommitInfo(
        sha=_optional_text(commit.get("sha")),
        committed_at=committed_at,
        message=_optional_text(commit_block.get("message")) if isinstance(commit_block, dict) else None,
    )


class _RepoHttpClient:
    def __init__(
        self,
        *,
        api_base_url: str = "https://api.github.com",
        token: str | None = None,
        timeout: int = 30,
        user_agent: str | None = None,
        proxy_url: str | None = None,
        request_retries: int = 3,
        retry_delay: float = 2.0,
    ) -> None:
        self.api_base_url = api_base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.user_agent = user_agent or _DEFAULT_USER_AGENT
        self.proxy_url = _normalize_proxy_url(proxy_url)
        self.request_retries = max(1, request_retries)
        self.retry_delay = max(0.0, retry_delay)
        self._opener = (
            build_opener(ProxyHandler({"http": self.proxy_url, "https": self.proxy_url}))
            if self.proxy_url
            else None
        )

    def api_json(
        self,
        path: str,
        *,
        allowed_statuses: tuple[int, ...] = (),
        default: Any = None,
    ) -> Any:
        headers = {"Accept": _JSON_ACCEPT}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        url = f"{self.api_base_url}{path}"
        try:
            result = self._request_text(
                url,
                accept=_JSON_ACCEPT,
                headers=headers,
                allowed_statuses=allowed_statuses,
                default=default,
            )
        except HTTPError as exc:
            raise RuntimeError(f"GitHub API request failed for {path}: HTTP {exc.code}") from exc
        except Exception as exc:
            raise RuntimeError(
                f"GitHub API request failed for {path}: {type(exc).__name__}: {exc}"
            ) from exc
        if not isinstance(result, str):
            return result
        return json.loads(result)

    def _request_text(
        self,
        url: str,
        *,
        accept: str,
        headers: dict[str, str] | None = None,
        allowed_statuses: tuple[int, ...] = (),
        default: Any = _UNSET,
    ) -> Any:
        request_headers = {
            "User-Agent": self.user_agent,
            "Accept": accept,
        }
        if headers:
            request_headers.update(headers)

        last_exc: BaseException | None = None
        for attempt in range(1, self.request_retries + 1):
            request = Request(url, headers=request_headers, method="GET")
            try:
                with self._open(request) as response:
                    return response.read().decode("utf-8", errors="ignore")
            except HTTPError as exc:
                if exc.code in allowed_statuses:
                    return None if default is _UNSET else default
                last_exc = exc
                logger.warning(
                    "GitHub fetch attempt %d/%d failed for %s: HTTP %s",
                    attempt,
                    self.request_retries,
                    url,
                    exc.code,
                )
                if exc.code not in _RETRYABLE_STATUS_CODES or attempt >= self.request_retries:
                    break
            except (URLError, TimeoutError, OSError, ValueError, IncompleteRead) as exc:
                last_exc = exc
                logger.warning(
                    "GitHub fetch attempt %d/%d failed for %s: %s",
                    attempt,
                    self.request_retries,
                    url,
                    exc,
                )
                if attempt >= self.request_retries:
                    break
            time.sleep(self.retry_delay)

        if last_exc is None:
            raise RuntimeError(f"Failed to fetch {url}")
        raise last_exc

    def _open(self, request: Request):
        if self._opener is not None:
            try:
                return self._opener.open(request, timeout=self.timeout)
            except (URLError, TimeoutError, OSError) as exc:
                logger.warning(
                    "GitHub proxy request failed via %s for %s, falling back to direct: %s",
                    self.proxy_url,
                    request.full_url,
                    exc,
                )
        return urlopen(request, timeout=self.timeout)


@dataclass
class GitHubRepoResourcesProvider:
    api_base_url: str = settings.github_api_base_url
    token: str | None = settings.github_token or None
    timeout: int = 30
    user_agent: str | None = settings.github_user_agent or None
    proxy_url: str | None = settings.github_proxy_url or None
    request_retries: int = 3
    retry_delay: float = 2.0
    _http: _RepoHttpClient = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._http = _RepoHttpClient(
            api_base_url=self.api_base_url,
            token=self.token,
            timeout=self.timeout,
            user_agent=self.user_agent,
            proxy_url=self.proxy_url,
            request_retries=self.request_retries,
            retry_delay=self.retry_delay,
        )

    def fetch_repo_resources(self, repo_full_name: str) -> RawRepoResources:
        repo_path = repo_full_name.strip().strip("/")
        if not repo_path:
            raise ValueError("repo_full_name is required")

        repo_data = self._fetch_repo_payload(repo_path)
        owner, repo = _split_repo_full_name(repo_path)
        topics_data = self._get_api_json(
            f"/repos/{owner}/{repo}/topics",
            allowed_statuses=(404,),
            default={},
        )
        topics = _extract_topics(topics_data)
        metadata = self._build_repo_metadata(repo_path, repo_data, topics)
        default_branch = _optional_text(repo_data.get("default_branch")) or "main"
        return RawRepoResources(
            metadata=metadata,
            default_branch=default_branch,
            readme=self.fetch_repo_readme(repo_path, ref=default_branch),
            releases=self.fetch_repo_releases(repo_path),
            tags=self.fetch_repo_tags(repo_path),
            last_commit=self.fetch_last_commit(repo_path, ref=default_branch),
        )

    def fetch_repo_metadata(self, repo_full_name: str) -> RawRepoMetadata:
        owner, repo = _split_repo_full_name(repo_full_name)
        topics_data = self._get_api_json(
            f"/repos/{owner}/{repo}/topics",
            allowed_statuses=(404,),
            default={},
        )
        topics = _extract_topics(topics_data)
        return self._build_repo_metadata(
            repo_full_name,
            self._fetch_repo_payload(repo_full_name),
            topics,
        )

    def fetch_default_branch(self, repo_full_name: str) -> str:
        repo_data = self._fetch_repo_payload(repo_full_name)
        return _optional_text(repo_data.get("default_branch")) or "main"

    def fetch_repo_readme(self, repo_full_name: str, *, ref: str | None = None) -> str | None:
        owner, repo = _split_repo_full_name(repo_full_name)
        query = urlencode({"ref": ref}) if ref else ""
        suffix = f"?{query}" if query else ""
        readme_data = self._get_api_json(
            f"/repos/{owner}/{repo}/readme{suffix}",
            allowed_statuses=(404,),
            default={},
        )
        return _extract_readme(readme_data)

    def fetch_repo_releases(self, repo_full_name: str, *, limit: int = 3) -> list[RawRepoRelease]:
        owner, repo = _split_repo_full_name(repo_full_name)
        releases_data = self._get_api_json(
            f"/repos/{owner}/{repo}/releases?{urlencode({'per_page': max(1, limit), 'page': 1})}",
            allowed_statuses=(404,),
            default=[],
        )
        return _extract_releases(releases_data)

    def fetch_repo_tags(self, repo_full_name: str, *, limit: int = 20) -> list[RawRepoTag]:
        owner, repo = _split_repo_full_name(repo_full_name)
        tags_data = self._get_api_json(
            f"/repos/{owner}/{repo}/tags?{urlencode({'per_page': max(1, limit), 'page': 1})}",
            allowed_statuses=(404,),
            default=[],
        )
        return _extract_tags(tags_data)

    def fetch_last_commit(self, repo_full_name: str, *, ref: str | None = None) -> RawCommitInfo:
        owner, repo = _split_repo_full_name(repo_full_name)
        query: list[tuple[str, str | int]] = []
        if ref:
            query.append(("sha", ref))
        query.append(("per_page", 1))
        commits_data = self._get_api_json(
            f"/repos/{owner}/{repo}/commits?{urlencode(query)}",
            allowed_statuses=(404, 409),
            default=[],
        )
        return _extract_last_commit(commits_data)

    def _fetch_repo_payload(self, repo_full_name: str) -> dict[str, Any]:
        owner, repo = _split_repo_full_name(repo_full_name)
        repo_data = self._get_api_json(f"/repos/{owner}/{repo}")
        if not isinstance(repo_data, dict):
            raise RuntimeError(f"Unexpected GitHub repo payload for {repo_full_name}")
        return repo_data

    def _build_repo_metadata(
        self,
        repo_full_name: str,
        repo_data: dict[str, Any],
        topics: list[str],
    ) -> RawRepoMetadata:
        normalized_repo_full_name = str(repo_data.get("full_name") or repo_full_name)
        return RawRepoMetadata(
            repo_full_name=normalized_repo_full_name,
            repo_url=_optional_text(repo_data.get("html_url")),
            description=_optional_text(repo_data.get("description")),
            primary_language=_optional_text(repo_data.get("language")),
            stars_total=_extract_stars_total(repo_data),
            topics=topics,
            homepage_url=_optional_text(repo_data.get("homepage")),
        )

    def _get_api_json(
        self,
        path: str,
        *,
        allowed_statuses: tuple[int, ...] = (),
        default: Any = None,
    ) -> Any:
        return self._http.api_json(path, allowed_statuses=allowed_statuses, default=default)


@dataclass
class StaticGitHubRepoResourcesProvider:
    repo_resources: dict[str, RawRepoResources] = field(default_factory=dict)

    def fetch_repo_resources(self, repo_full_name: str) -> RawRepoResources:
        try:
            return self.repo_resources[repo_full_name]
        except KeyError as exc:
            raise KeyError(f"Missing static repo resources for {repo_full_name}") from exc

    def fetch_repo_metadata(self, repo_full_name: str) -> RawRepoMetadata:
        return self.fetch_repo_resources(repo_full_name).metadata

    def fetch_default_branch(self, repo_full_name: str) -> str:
        return self.fetch_repo_resources(repo_full_name).default_branch or "main"

    def fetch_repo_readme(self, repo_full_name: str, *, ref: str | None = None) -> str | None:
        del ref
        return self.fetch_repo_resources(repo_full_name).readme

    def fetch_repo_releases(self, repo_full_name: str, *, limit: int = 3) -> list[RawRepoRelease]:
        return list(self.fetch_repo_resources(repo_full_name).releases[: max(1, limit)])

    def fetch_repo_tags(self, repo_full_name: str, *, limit: int = 20) -> list[RawRepoTag]:
        return list(self.fetch_repo_resources(repo_full_name).tags[: max(1, limit)])

    def fetch_last_commit(self, repo_full_name: str, *, ref: str | None = None) -> RawCommitInfo:
        del ref
        return self.fetch_repo_resources(repo_full_name).last_commit
