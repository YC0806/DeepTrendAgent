from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class CronGitHubAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.root = Path(temp_dir.name)
        self.env_file = self.root / "deeptrend.env"
        self.env_file.write_text(
            f"DEEPTREND_ARTIFACT_ROOT={shlex.quote(str(self.root / 'artifacts'))}\n"
            "GITHUB_TOKEN=stale-config-token\n",
            encoding="utf-8",
        )
        self.write_command("flock", 'exit "$TEST_FLOCK_STATUS"')
        self.write_command(
            "gh",
            '[[ -z "${GH_TOKEN+x}${GITHUB_TOKEN+x}" ]]\n'
            '[[ "$GH_PROMPT_DISABLED" == 1 ]]\n'
            '[[ "$*" == "auth token --hostname github.com --no-refresh=false" ]]\n'
            'echo "gh called" >&2\n'
            'printf "%s\\n" "$TEST_GH_TOKEN"\n'
            'exit "$TEST_GH_STATUS"',
        )
        self.write_command(
            "python3",
            '[[ "$*" == "-m src.scripts.run_pipeline --since daily --language all --output-language 简体中文" ]]\n'
            '[[ "$GITHUB_TOKEN" == "$TEST_GH_TOKEN" && -n "$GITHUB_TOKEN" ]]\n'
            'echo "pipeline started"',
        )

        self.write_command("opencode", "exit 99")

    def write_command(self, name: str, body: str) -> None:
        path = self.root / name
        path.write_text(f"#!/bin/bash\nset -eu\n{body}\n", encoding="utf-8")
        path.chmod(0o700)

    def run_cron(
        self, *, token: str, gh_status: int = 0, flock_status: int = 0
    ) -> subprocess.CompletedProcess[str]:
        env = {
            "PATH": f"{self.root}{os.pathsep}{os.defpath}",
            "DEEPTREND_ENV_FILE": str(self.env_file),
            "GH_TOKEN": "stale-environment-token",
            "TEST_GH_TOKEN": token,
            "TEST_GH_STATUS": str(gh_status),
            "TEST_FLOCK_STATUS": str(flock_status),
        }
        return subprocess.run(
            [str(REPO_ROOT / "bin" / "run-deeptrend")],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_each_start_fetches_a_token_without_logging_it(self) -> None:
        for token in ("first-test-token", "second-test-token"):
            with self.subTest(token=token):
                result = self.run_cron(token=token)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "pipeline started\n")
                self.assertEqual(result.stderr, "gh called\n")

    def test_token_lookup_failure_stops_before_opencode(self) -> None:
        for token, status in (("", 0), ("failed-test-token", 1)):
            with self.subTest(status=status):
                result = self.run_cron(token=token, gh_status=status)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, "")
                self.assertIn("gh called\n", result.stderr)
                self.assertIn("gh auth login --hostname github.com --expiring", result.stderr)
                self.assertNotIn("failed-test-token", result.stderr)

    def test_overlapping_run_skips_token_lookup(self) -> None:
        result = self.run_cron(token="unused-test-token", flock_status=1)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "DeepTrend is already running; skipping this trigger.\n")
