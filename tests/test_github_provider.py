from __future__ import annotations

import json
import unittest
from http.client import IncompleteRead

from deeptrend.models import (
    RawCommitInfo,
    RawRepoMetadata,
    RawRepoFileContent,
    RawRepoResources,
    RawRepoTag,
    RawTrendingEntry,
    RawTrendingSnapshot,
)
from deeptrend.provider import (
    GitHubRepoResourcesProvider,
    GitHubTrendingArchiveProvider,
    GitHubTrendingProvider,
    StaticGitRepoProvider,
    StaticGitHubRepoResourcesProvider,
    StaticGitHubTrendingArchiveProvider,
    StaticGitHubTrendingProvider,
)
from deeptrend.provider.github.repo import _RepoHttpClient
from deeptrend.provider.github.trending import _TrendingHttpClient


class _FakeResponse:
    def __init__(self, reads: list[object]) -> None:
        self._reads = list(reads)

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        item = self._reads.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class GitHubProviderTests(unittest.TestCase):
    def test_trending_http_client_retries_incomplete_read(self) -> None:
        client = _TrendingHttpClient(request_retries=2, retry_delay=0)
        responses = iter(
            [
                _FakeResponse([IncompleteRead(b"<article", 10)]),
                _FakeResponse([b"<article class=\"Box-row\"></article>"]),
            ]
        )
        client._open = lambda request: next(responses)

        html = client.get_html("https://github.example.com/trending")

        self.assertIn("Box-row", html)

    def test_repo_http_client_retries_incomplete_read(self) -> None:
        client = _RepoHttpClient(api_base_url="https://api.example.com", request_retries=2, retry_delay=0)
        responses = iter(
            [
                _FakeResponse([IncompleteRead(b'{"full_name"', 10)]),
                _FakeResponse([json.dumps({"full_name": "acme/agent-kit"}).encode("utf-8")]),
            ]
        )
        client._open = lambda request: next(responses)

        payload = client.api_json("/repos/acme/agent-kit")

        self.assertEqual(payload, {"full_name": "acme/agent-kit"})

    def test_package_exports_new_github_provider_names(self) -> None:
        self.assertEqual(GitHubTrendingProvider.__name__, "GitHubTrendingProvider")
        self.assertEqual(GitHubTrendingArchiveProvider.__name__, "GitHubTrendingArchiveProvider")
        self.assertEqual(GitHubRepoResourcesProvider.__name__, "GitHubRepoResourcesProvider")
        self.assertTrue(callable(getattr(StaticGitHubTrendingProvider, "fetch_current_snapshot", None)))
        self.assertTrue(callable(getattr(StaticGitHubTrendingArchiveProvider, "fetch_archive_snapshot", None)))
        self.assertTrue(callable(getattr(StaticGitHubRepoResourcesProvider, "fetch_repo_resources", None)))

    def test_static_trending_provider_returns_snapshot(self) -> None:
        snapshot = RawTrendingSnapshot(entries=[RawTrendingEntry(repo_full_name="acme/agent-kit", rank=1)])
        provider = StaticGitHubTrendingProvider(snapshot=snapshot)

        result = provider.fetch_current_snapshot(
            snapshot_date="2026-04-02",
            since="daily",
            language="python",
        )

        self.assertIs(result, snapshot)

    def test_static_trending_archive_provider_returns_matching_snapshot(self) -> None:
        snapshot = RawTrendingSnapshot(entries=[RawTrendingEntry(repo_full_name="acme/agent-kit", rank=1)])
        provider = StaticGitHubTrendingArchiveProvider(
            snapshots={("2026-04-01", "daily", "python"): snapshot}
        )

        result = provider.fetch_archive_snapshot(
            snapshot_date="2026-04-01",
            since="daily",
            language="python",
        )

        self.assertIs(result, snapshot)
        self.assertIsNone(
            provider.fetch_archive_snapshot(
                snapshot_date="2026-03-31",
                since="daily",
                language="python",
            )
        )

    def test_static_repo_resources_provider_returns_matching_resources(self) -> None:
        resources = RawRepoResources(
            metadata=RawRepoMetadata(repo_full_name="acme/agent-kit"),
            readme="readme",
            last_commit=RawCommitInfo(sha="abc123"),
            tags=[RawRepoTag(name="v1.0.0", commit_sha="abc123")],
            default_branch="main",
        )
        provider = StaticGitHubRepoResourcesProvider(repo_resources={"acme/agent-kit": resources})

        result = provider.fetch_repo_resources("acme/agent-kit")

        self.assertIs(result, resources)

    def test_static_repo_resources_provider_raises_for_missing_repo(self) -> None:
        provider = StaticGitHubRepoResourcesProvider()

        with self.assertRaisesRegex(KeyError, "Missing static repo resources for acme/missing"):
            provider.fetch_repo_resources("acme/missing")

    def test_github_trending_provider_parses_html_snapshot(self) -> None:
        provider = GitHubTrendingProvider(base_url="https://github.example.com")
        provider._fetch_html = lambda url: """
<article class="Box-row">
  <h2><a href="/acme/agent-kit">agent-kit</a></h2>
  <span>1,234 stars today</span>
</article>
<article class="Box-row">
  <h2><a href="/acme/web-utils">web-utils</a></h2>
  <span>98 stars this week</span>
</article>
"""

        snapshot = provider.fetch_current_snapshot(
            snapshot_date="2026-04-02",
            since="daily",
            language="python",
        )

        self.assertEqual(snapshot.source_url, "https://github.example.com/trending/python?since=daily")
        self.assertEqual([entry.repo_full_name for entry in snapshot.entries], ["acme/agent-kit", "acme/web-utils"])
        self.assertEqual(snapshot.entries[0].rank, 1)
        self.assertEqual(snapshot.entries[0].stars_period, 1234)
        self.assertEqual(snapshot.entries[1].repo_url, "https://github.example.com/acme/web-utils")

    def test_github_trending_provider_respects_default_limit(self) -> None:
        provider = GitHubTrendingProvider(base_url="https://github.example.com", default_limit=1)
        provider._fetch_html = lambda url: """
<article class="Box-row"><h2><a href="/acme/agent-kit">agent-kit</a></h2></article>
<article class="Box-row"><h2><a href="/acme/web-utils">web-utils</a></h2></article>
"""

        snapshot = provider.fetch_current_snapshot(
            snapshot_date="2026-04-02",
            since="daily",
            language="python",
        )

        self.assertEqual([entry.repo_full_name for entry in snapshot.entries], ["acme/agent-kit"])

    def test_github_trending_provider_uses_fallback_fetcher(self) -> None:
        provider = GitHubTrendingProvider(
            base_url="https://github.example.com",
            html_fallback_fetcher=lambda url: """
<article class="Box-row"><h2><a href="/acme/fallback-repo">fallback-repo</a></h2></article>
""",
        )
        provider._http.get_html = lambda url: (_ for _ in ()).throw(OSError("boom"))

        snapshot = provider.fetch_current_snapshot(
            snapshot_date="2026-04-02",
            since="daily",
            language="python",
        )

        self.assertEqual([entry.repo_full_name for entry in snapshot.entries], ["acme/fallback-repo"])

    def test_github_repo_resources_provider_maps_api_payloads(self) -> None:
        provider = GitHubRepoResourcesProvider(api_base_url="https://api.example.com")
        readme_b64 = "IyBUaXRsZQoKQWdlbnQga2l0IHJlYWRtZS4="
        payload_by_path = {
            "/repos/acme/agent-kit": {
                "full_name": "acme/agent-kit",
                "html_url": "https://github.example.com/acme/agent-kit",
                "description": "Agent toolkit",
                "language": "Python",
                "stargazers_count": 1200,
                "homepage": "https://acme.dev/agent-kit",
                "default_branch": "main",
            },
            "/repos/acme/agent-kit/topics": {"names": ["ai", "agent"]},
            "/repos/acme/agent-kit/readme?ref=main": {"content": readme_b64},
            "/repos/acme/agent-kit/releases?per_page=3&page=1": [
                {
                    "name": "v1.0.0",
                    "body": "First release",
                    "published_at": "2026-04-01T00:00:00Z",
                }
            ],
            "/repos/acme/agent-kit/tags?per_page=20&page=1": [
                {
                    "name": "v1.0.0",
                    "commit": {"sha": "abc123"},
                }
            ],
            "/repos/acme/agent-kit/commits?sha=main&per_page=1": [
                {
                    "sha": "abc123",
                    "commit": {
                        "committer": {"date": "2026-04-02T00:00:00Z"},
                        "message": "ship stable release",
                    },
                }
            ],
        }
        provider._get_api_json = lambda path, **kwargs: payload_by_path[path]

        resources = provider.fetch_repo_resources("acme/agent-kit")

        self.assertEqual(resources.metadata.repo_full_name, "acme/agent-kit")
        self.assertEqual(resources.metadata.primary_language, "Python")
        self.assertEqual(resources.metadata.stars_total, 1200)
        self.assertEqual(resources.metadata.topics, ["ai", "agent"])
        self.assertEqual(resources.default_branch, "main")
        self.assertEqual(resources.readme, "Title Agent kit readme.")
        self.assertEqual(resources.releases[0].title, "v1.0.0")
        self.assertEqual(resources.tags[0].name, "v1.0.0")
        self.assertEqual(resources.last_commit.sha, "abc123")
        self.assertEqual(resources.last_commit.committed_at, "2026-04-02T00:00:00Z")
        self.assertEqual(resources.last_commit.message, "ship stable release")

    def test_github_trending_archive_provider_normalizes_archive_payload(self) -> None:
        archive_repo = "acme/trending-archive"
        provider = GitHubTrendingArchiveProvider(
            base_url="https://github.example.com",
            archive_repo_full_name=archive_repo,
            archive_ref="main",
            git_provider=StaticGitRepoProvider(
                file_contents={
                    (
                        archive_repo,
                        "archive/repository/2026/2026-04-01.json",
                        "main",
                    ): RawRepoFileContent(
                        path="archive/repository/2026/2026-04-01.json",
                        ref="main",
                        content=(
                            '{"Python":[{"full_name":"acme/agent-kit","url":"https://github.com/acme/agent-kit"},'
                            '{"repository":"acme/web-utils"}]}'
                        ),
                    )
                }
            ),
        )

        snapshot = provider.fetch_archive_snapshot(
            snapshot_date="2026-04-01",
            since="daily",
            language="python",
        )

        assert snapshot is not None
        self.assertEqual(
            snapshot.source_url,
            "https://github.example.com/acme/trending-archive/blob/main/archive/repository/2026/2026-04-01.json",
        )
        self.assertEqual([entry.repo_full_name for entry in snapshot.entries], ["acme/agent-kit", "acme/web-utils"])
        self.assertEqual(snapshot.entries[1].repo_url, "https://github.example.com/acme/web-utils")

    def test_github_trending_archive_provider_limits_entries_to_top_25(self) -> None:
        archive_repo = "acme/trending-archive"
        provider = GitHubTrendingArchiveProvider(
            archive_repo_full_name=archive_repo,
            archive_ref="main",
            git_provider=StaticGitRepoProvider(
                file_contents={
                    (
                        archive_repo,
                        "archive/repository/2026/2026-04-01.json",
                        "main",
                    ): RawRepoFileContent(
                        path="archive/repository/2026/2026-04-01.json",
                        ref="main",
                        content='{"Python":['
                        + ",".join(f'{{"full_name":"acme/repo-{index}"}}' for index in range(30))
                        + "]}",
                    )
                }
            ),
        )

        snapshot = provider.fetch_archive_snapshot(
            snapshot_date="2026-04-01",
            since="daily",
            language="python",
        )

        assert snapshot is not None
        self.assertEqual(len(snapshot.entries), 25)
        self.assertEqual(snapshot.entries[0].repo_full_name, "acme/repo-0")
        self.assertEqual(snapshot.entries[-1].repo_full_name, "acme/repo-24")

    def test_github_trending_archive_provider_returns_none_for_missing_snapshot(self) -> None:
        provider = GitHubTrendingArchiveProvider(git_provider=StaticGitRepoProvider())

        self.assertIsNone(
            provider.fetch_archive_snapshot(
                snapshot_date="2026-04-01",
                since="daily",
                language="python",
            )
        )

    def test_github_trending_archive_provider_returns_none_for_non_daily_since(self) -> None:
        provider = GitHubTrendingArchiveProvider()

        self.assertIsNone(
            provider.fetch_archive_snapshot(
                snapshot_date="2026-04-01",
                since="weekly",
                language="python",
            )
        )


if __name__ == "__main__":
    unittest.main()
