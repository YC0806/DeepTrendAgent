from __future__ import annotations

import unittest

from deeptrend.models import RawCommitInfo, RawRepoFileContent, RawRepoTreeEntry
from deeptrend.provider import StaticGitRepoProvider
from deeptrend.tools import (
    get_git_repo_commit_history,
    get_git_repo_diff,
    get_git_repo_file_content,
    get_git_repo_last_commit_for_path,
    get_git_repo_tree,
)


class GitToolTests(unittest.TestCase):
    def test_tool_exports_cover_git_interfaces(self) -> None:
        import deeptrend.tools as tools

        self.assertTrue(callable(tools.get_git_repo_file_content))
        self.assertTrue(callable(tools.get_git_repo_tree))
        self.assertTrue(callable(tools.get_git_repo_commit_history))
        self.assertTrue(callable(tools.get_git_repo_last_commit_for_path))
        self.assertTrue(callable(tools.get_git_repo_diff))

    def test_git_tools_delegate_to_provider(self) -> None:
        provider = StaticGitRepoProvider(
            file_contents={
                ("acme/agent-kit", "README.md", "main"): RawRepoFileContent(
                    path="README.md",
                    ref="main",
                    content="readme",
                )
            },
            trees={
                ("acme/agent-kit", "docs", "main"): [
                    RawRepoTreeEntry(path="docs/intro.md", entry_type="blob", ref="main", sha="abc123")
                ]
            },
            commit_histories={
                ("acme/agent-kit", "README.md", "main", 2): [
                    RawCommitInfo(sha="abc123", committed_at="2026-04-01T00:00:00Z", message="update readme")
                ],
                ("acme/agent-kit", "README.md", "main", 1): [
                    RawCommitInfo(sha="abc123", committed_at="2026-04-01T00:00:00Z", message="update readme")
                ],
            },
            diffs={("acme/agent-kit", "HEAD^", "HEAD", None): " README.md | 2 ++"},
        )

        self.assertEqual(
            get_git_repo_file_content("acme/agent-kit", "README.md", ref="main", provider=provider).content,
            "readme",
        )
        self.assertEqual(
            get_git_repo_tree("acme/agent-kit", path="docs", ref="main", provider=provider)[0].path,
            "docs/intro.md",
        )
        self.assertEqual(
            get_git_repo_commit_history(
                "acme/agent-kit",
                path="README.md",
                ref="main",
                limit=2,
                provider=provider,
            )[0].message,
            "update readme",
        )
        self.assertEqual(
            get_git_repo_last_commit_for_path(
                "acme/agent-kit",
                "README.md",
                ref="main",
                provider=provider,
            ).sha,
            "abc123",
        )
        self.assertIn(
            "README.md",
            get_git_repo_diff(
                "acme/agent-kit",
                base_ref="HEAD^",
                head_ref="HEAD",
                provider=provider,
            ),
        )


if __name__ == "__main__":
    unittest.main()
