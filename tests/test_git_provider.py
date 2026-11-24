from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from deeptrend.config import Settings
from deeptrend.models import RawCommitInfo, RawRepoFileContent, RawRepoTreeEntry
from deeptrend.provider import GitRepoProvider, StaticGitRepoProvider


def _run_git(repo_dir: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_dir), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _init_test_repo() -> tuple[tempfile.TemporaryDirectory[str], Path]:
    tmpdir = tempfile.TemporaryDirectory()
    repo_dir = Path(tmpdir.name) / "agent-kit"
    repo_dir.mkdir(parents=True, exist_ok=True)
    _run_git(repo_dir, "init")
    _run_git(repo_dir, "config", "user.email", "tests@example.com")
    _run_git(repo_dir, "config", "user.name", "DeepTrend Tests")
    _run_git(repo_dir, "checkout", "-b", "main")

    (repo_dir / "README.md").write_text("# Agent Kit\n", encoding="utf-8")
    (repo_dir / "docs").mkdir()
    (repo_dir / "docs" / "intro.md").write_text("intro\n", encoding="utf-8")
    _run_git(repo_dir, "add", "README.md", "docs/intro.md")
    _run_git(repo_dir, "commit", "-m", "initial import")

    (repo_dir / "README.md").write_text("# Agent Kit\n\nToolkit\n", encoding="utf-8")
    _run_git(repo_dir, "add", "README.md")
    _run_git(repo_dir, "commit", "-m", "update readme")
    return tmpdir, repo_dir


class GitProviderTests(unittest.TestCase):
    def test_git_repo_provider_default_cache_root_is_workspace_tmp(self) -> None:
        expected = Path(__file__).resolve().parents[1] / "tmp" / "git-cache"
        self.assertEqual(Path(Settings().deeptrend_git_cache_root), expected)

    def test_package_exports_git_provider_names(self) -> None:
        self.assertEqual(GitRepoProvider.__name__, "GitRepoProvider")
        self.assertTrue(callable(getattr(StaticGitRepoProvider, "fetch_file_content", None)))

    def test_static_git_provider_returns_stubbed_values(self) -> None:
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
                ("acme/agent-kit", "README.md", "main", 1): [
                    RawCommitInfo(sha="abc123", committed_at="2026-04-01T00:00:00Z", message="update readme")
                ]
            },
            diffs={("acme/agent-kit", "HEAD^", "HEAD", None): " README.md | 2 ++"},
        )

        self.assertEqual(
            provider.fetch_file_content("acme/agent-kit", "README.md", ref="main").content,
            "readme",
        )
        self.assertEqual(provider.fetch_tree("acme/agent-kit", path="docs", ref="main")[0].path, "docs/intro.md")
        self.assertEqual(
            provider.fetch_last_commit_for_path("acme/agent-kit", "README.md", ref="main").message,
            "update readme",
        )
        self.assertIn("README.md", provider.fetch_diff("acme/agent-kit", base_ref="HEAD^", head_ref="HEAD"))

    def test_git_repo_provider_reads_file_tree_and_history_from_local_repo(self) -> None:
        tmpdir, repo_dir = _init_test_repo()
        self.addCleanup(tmpdir.cleanup)

        provider = GitRepoProvider(repo_paths={"acme/agent-kit": str(repo_dir)})

        readme = provider.fetch_file_content("acme/agent-kit", "README.md", ref="HEAD")
        tree = provider.fetch_tree("acme/agent-kit", path="docs", ref="HEAD")
        history = provider.fetch_commit_history("acme/agent-kit", path="README.md", ref="HEAD", limit=2)
        last_commit = provider.fetch_last_commit_for_path("acme/agent-kit", "README.md", ref="HEAD")
        diff = provider.fetch_diff("acme/agent-kit", base_ref="HEAD^", head_ref="HEAD")

        assert readme.content is not None
        self.assertIn("Toolkit", readme.content)
        self.assertEqual(tree[0].path, "docs/intro.md")
        self.assertEqual(history[0].message, "update readme")
        self.assertEqual(last_commit.sha, history[0].sha)
        self.assertIn("README.md", diff)


if __name__ == "__main__":
    unittest.main()
