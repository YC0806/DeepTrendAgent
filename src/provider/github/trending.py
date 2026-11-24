from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from http.client import IncompleteRead
from html import unescape
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener, urlopen

from ...config import settings
from ...models import RawTrendingEntry, RawTrendingSnapshot

logger = logging.getLogger(__name__)

_HTML_ACCEPT = "text/html,application/xhtml+xml"
_DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; TrendObserver/0.1)"


def _normalize_proxy_url(value: str | None) -> str:
    proxy_url = str(value or "").strip()
    if not proxy_url:
        return ""
    if "://" not in proxy_url:
        return f"http://{proxy_url}"
    return proxy_url


def _clean_text(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    text = unescape(text)
    return " ".join(text.split())


def _parse_int(value: str) -> int | None:
    digits = re.sub(r"[^\d]", "", value or "")
    return int(digits) if digits else None


def _extract_trending_entries(html: str, *, base_url: str, limit: int) -> list[RawTrendingEntry]:
    articles = re.findall(
        r"<article\b[^>]*class=\"[^\"]*\bBox-row\b[^\"]*\"[^>]*>(.*?)</article>",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    entries: list[RawTrendingEntry] = []
    for rank, article in enumerate(articles[: max(0, limit)], start=1):
        match = re.search(
            r"<h2\b[^>]*>.*?<a\b[^>]*href=\"/([^\"#?]+/[^\"#?]+)\"",
            article,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            continue
        repo_full_name = match.group(1).strip().strip("/")
        stars_match = re.search(
            r"([0-9][0-9,]*)\s+stars?\s+(?:today|this week|this month)",
            _clean_text(article),
            flags=re.IGNORECASE,
        )
        entries.append(
            RawTrendingEntry(
                rank=rank,
                repo_full_name=repo_full_name,
                repo_url=f"{base_url}/{repo_full_name}",
                stars_period=_parse_int(stars_match.group(1)) if stars_match else None,
            )
        )
    return entries


class _TrendingHttpClient:
    def __init__(
        self,
        *,
        timeout: int = 30,
        user_agent: str | None = None,
        proxy_url: str | None = None,
        request_retries: int = 3,
        retry_delay: float = 2.0,
    ) -> None:
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

    def get_html(self, url: str) -> str:
        last_exc: BaseException | None = None
        for attempt in range(1, self.request_retries + 1):
            request = Request(
                url,
                headers={
                    "User-Agent": self.user_agent,
                    "Accept": _HTML_ACCEPT,
                },
                method="GET",
            )
            try:
                with self._open(request) as response:
                    return response.read().decode("utf-8", errors="ignore")
            except (HTTPError, URLError, TimeoutError, OSError, ValueError, IncompleteRead) as exc:
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
class GitHubTrendingProvider:
    base_url: str = settings.github_base_url
    timeout: int = 30
    user_agent: str | None = settings.github_user_agent or None
    proxy_url: str | None = settings.github_proxy_url or None
    request_retries: int = 3
    retry_delay: float = 2.0
    default_limit: int = 50
    html_fallback_fetcher: Callable[[str], str] | None = None
    _http: _TrendingHttpClient = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        self._http = _TrendingHttpClient(
            timeout=self.timeout,
            user_agent=self.user_agent,
            proxy_url=self.proxy_url,
            request_retries=self.request_retries,
            retry_delay=self.retry_delay,
        )

    def fetch_current_snapshot(
        self,
        *,
        snapshot_date: str | None = None,
        since: str,
        language: str,
    ) -> RawTrendingSnapshot:
        del snapshot_date
        source_url = self._build_trending_url(since=since, language=language)
        html = self._fetch_html(source_url)
        return RawTrendingSnapshot(
            entries=_extract_trending_entries(
                html,
                base_url=self.base_url,
                limit=max(0, self.default_limit),
            ),
            source_url=source_url,
        )

    def _build_trending_url(self, *, since: str, language: str) -> str:
        language = language.strip()
        path = f"{self.base_url}/trending"
        if language and language != "all":
            path = f"{path}/{language}"
        return f"{path}?since={since}"

    def _fetch_html(self, url: str) -> str:
        try:
            return self._http.get_html(url)
        except Exception as exc:
            if self.html_fallback_fetcher is None:
                raise
            logger.warning("GitHub direct fetch failed for %s, trying fallback fetcher: %s", url, exc)
            html = self.html_fallback_fetcher(url)
            if html:
                logger.info("GitHub fetch fallback succeeded for %s", url)
                return html
            raise


@dataclass
class StaticGitHubTrendingProvider:
    snapshot: RawTrendingSnapshot

    def fetch_current_snapshot(
        self,
        *,
        snapshot_date: str,
        since: str,
        language: str,
    ) -> RawTrendingSnapshot:
        del snapshot_date, since, language
        return self.snapshot
