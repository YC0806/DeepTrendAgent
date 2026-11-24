from __future__ import annotations

import unittest

from deeptrend.models import (
    RawCommitInfo,
    RawRepoMetadata,
    RawRepoRelease,
    RawRepoResources,
    RawRepoTag,
    RawTrendingEntry,
    RawTrendingSnapshot,
)
from deeptrend.provider import (
    StaticGitHubRepoResourcesProvider,
    StaticGitHubTrendingArchiveProvider,
    StaticGitHubTrendingProvider,
)
from deeptrend.tools import (
    annotate_snapshot_diff,
    build_github_repo_context,
    get_current_github_snapshot,
    get_github_archive_snapshot,
    get_github_repo_default_branch,
    get_github_repo_last_commit,
    get_github_repo_metadata,
    get_github_repo_releases,
    get_github_repo_resources,
    get_github_repo_tags,
)


class GitHubToolTests(unittest.TestCase):
    def test_tool_exports_cover_github_only_interfaces(self) -> None:
        import deeptrend.tools as tools

        self.assertTrue(callable(tools.get_current_github_snapshot))
        self.assertTrue(callable(tools.get_github_archive_snapshot))
        self.assertTrue(callable(tools.get_github_repo_resources))
        self.assertTrue(callable(tools.get_github_repo_metadata))
        self.assertTrue(callable(tools.get_github_repo_releases))
        self.assertTrue(callable(tools.get_github_repo_tags))
        self.assertTrue(callable(tools.get_github_repo_default_branch))
        self.assertTrue(callable(tools.get_github_repo_last_commit))
        self.assertTrue(callable(tools.annotate_snapshot_diff))
        self.assertTrue(callable(tools.build_github_repo_context))
        self.assertFalse(hasattr(tools, "build_github_snapshot_diff"))

    def test_trending_and_archive_tools_delegate_to_providers(self) -> None:
        current_snapshot = RawTrendingSnapshot(entries=[RawTrendingEntry(repo_full_name="acme/current", rank=1)])
        archive_snapshot = RawTrendingSnapshot(entries=[RawTrendingEntry(repo_full_name="acme/archive", rank=1)])

        current = get_current_github_snapshot(
            "2026-04-03",
            "daily",
            "python",
            provider=StaticGitHubTrendingProvider(snapshot=current_snapshot),
        )
        archive = get_github_archive_snapshot(
            "2026-04-02",
            "daily",
            "python",
            provider=StaticGitHubTrendingArchiveProvider(
                snapshots={("2026-04-02", "daily", "python"): archive_snapshot}
            ),
        )

        self.assertEqual(current.snapshot_date, "2026-04-03")
        self.assertEqual(current.source, "github-trending")
        self.assertEqual([entry.repo_full_name for entry in current.entries], ["acme/current"])
        self.assertIs(archive, archive_snapshot)

    def test_repo_resources_tool_and_context_builder_map_github_data(self) -> None:
        raw_resources = RawRepoResources(
            metadata=RawRepoMetadata(
                repo_full_name="acme/agent-kit",
                repo_url="https://github.com/acme/agent-kit",
                description="Agent orchestration toolkit for LLM workflows.",
                primary_language="Python",
                stars_total=1200,
                topics=["ai", "agent", "workflow"],
                homepage_url="https://acme.dev/agent-kit",
            ),
            readme="Agent orchestration toolkit for LLM workflows.",
            releases=[
                RawRepoRelease(
                    title="v1.0.0",
                    notes="First stable release",
                    published_at="2026-04-01T00:00:00Z",
                )
            ],
            tags=[RawRepoTag(name="v1.0.0", commit_sha="abc123")],
            last_commit=RawCommitInfo(sha="abc123", committed_at="2026-04-02T00:00:00Z"),
            default_branch="main",
        )

        provider = StaticGitHubRepoResourcesProvider(repo_resources={"acme/agent-kit": raw_resources})
        fetched = get_github_repo_resources("acme/agent-kit", provider=provider)
        metadata = get_github_repo_metadata("acme/agent-kit", provider=provider)
        releases = get_github_repo_releases("acme/agent-kit", provider=provider)
        tags = get_github_repo_tags("acme/agent-kit", provider=provider)
        default_branch = get_github_repo_default_branch("acme/agent-kit", provider=provider)
        last_commit = get_github_repo_last_commit("acme/agent-kit", provider=provider)
        context = build_github_repo_context(fetched)

        self.assertEqual(metadata.repo_full_name, "acme/agent-kit")
        self.assertEqual(default_branch, "main")
        self.assertEqual(releases[0].title, "v1.0.0")
        self.assertEqual(tags[0].name, "v1.0.0")
        self.assertEqual(last_commit.sha, "abc123")
        self.assertEqual(context.repo_full_name, "acme/agent-kit")
        self.assertEqual(context.repo_url, "https://github.com/acme/agent-kit")
        self.assertEqual(context.primary_language, "Python")
        self.assertEqual(context.stars_total, 1200)
        self.assertEqual(context.topics, ["ai", "agent", "workflow"])
        self.assertEqual(context.readme, "Agent orchestration toolkit for LLM workflows.")
        self.assertEqual(context.last_commit_hash, "abc123")
        self.assertEqual(context.last_commit_at, "2026-04-02T00:00:00Z")
        self.assertEqual(context.tag_names, ["v1.0.0"])
        assert context.release_notes is not None
        self.assertIn("v1.0.0", context.release_notes)
        self.assertIn("First stable release", context.release_notes)

    def test_annotate_diff_marks_new_repos_when_history_is_missing(self) -> None:
        current = get_current_github_snapshot(
            "2026-04-03",
            "daily",
            "python",
            provider=StaticGitHubTrendingProvider(
                snapshot=RawTrendingSnapshot(
                    entries=[
                        RawTrendingEntry(repo_full_name="acme/agent-kit"),
                        RawTrendingEntry(repo_full_name="acme/web-utils", rank=4, stars_period=25),
                    ],
                    source_url="https://github.com/trending/python?since=daily",
                )
            ),
        )
        annotated = annotate_snapshot_diff(current, None, history_source="archive_bootstrap")

        self.assertEqual(len(current.entries), 2)
        self.assertEqual(current.entries[0].rank, 1)
        self.assertEqual(current.entries[0].repo_url, "https://github.com/acme/agent-kit")
        self.assertEqual(current.entries[0].stars_period, 0)
        self.assertEqual(annotated.previous_snapshot_date, None)
        self.assertEqual(annotated.history_source, "archive_bootstrap")
        self.assertTrue(all(entry.is_new for entry in annotated.entries))


if __name__ == "__main__":
    unittest.main()
