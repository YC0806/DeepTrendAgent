from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import src  # noqa: F401
from src.scripts._cli_common import default_snapshot_date, init_run_layout

from deeptrend.models import (
    Delivery,
    RawCommitInfo,
    RawRepoMetadata,
    RawRepoRelease,
    RawRepoResources,
    RawRepoTag,
    RawTrendingEntry,
    RawTrendingSnapshot,
    RepoAnalysis,
    TrendingEntry,
    TrendingSnapshot,
    TrendReport,
    TrendRun,
    utcnow_iso,
)
from deeptrend.tools import report_attachment_filename


REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = next(
    child
    for child in REPO_ROOT.iterdir()
    if child.is_dir()
    and (child / "__init__.py").is_file()
    and (child / "config.py").is_file()
    and (child / "models.py").is_file()
    and (child / "provider").is_dir()
    and (child / "tools").is_dir()
    and (child / "scripts").is_dir()
)


def _run_script(script_path: Path, *args: str, env_overrides: dict[str, str] | None = None) -> dict:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    if env_overrides:
        env.update(env_overrides)
    result = subprocess.run(
        [sys.executable, str(script_path), *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


class InitRunScriptTests(unittest.TestCase):
    def test_creates_flat_layout_with_canonical_run_id(self) -> None:
        snapshot_date = default_snapshot_date()
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = _run_script(
                PACKAGE_DIR / "scripts" / "init_run.py",
                "--artifact-root",
                tmpdir,
            )
            run_dir = Path(payload["run_dir"])
            self.assertEqual(payload["snapshot_date"], snapshot_date)
            self.assertEqual(payload["run_slug"], "github-trending-daily-all")
            self.assertEqual(payload["run_id"], f"{snapshot_date}__github-trending-daily-all")
            self.assertEqual(payload["environment"]["DEEPTREND_RUN_DIR"], str(run_dir))
            self.assertTrue(run_dir.is_dir())
            self.assertTrue((run_dir / "repo").is_dir())
            # Flat layout — no stages/, shared/, analysis/, report/, delivery/, logs/
            for legacy in ("shared", "stages", "analysis", "report", "delivery", "logs", "repo_context"):
                self.assertFalse((run_dir / legacy).exists(), f"unexpected legacy dir: {legacy}")

    def test_run_slug_is_filesystem_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = _run_script(
                PACKAGE_DIR / "scripts" / "init_run.py",
                "--source",
                "GitHub Trending",
                "--since",
                "weekly",
                "--language",
                "C++",
                "--artifact-root",
                tmpdir,
            )
        self.assertEqual(payload["run_slug"], "github-trending-weekly-c-plus-plus")


class FetchSnapshotScriptTests(unittest.TestCase):
    def _previous_snapshot(self) -> TrendingSnapshot:
        return TrendingSnapshot(
            snapshot_date="2026-04-02",
            since="daily",
            language="python",
            source="github-trending",
            entries=[
                TrendingEntry(
                    rank=1,
                    repo_full_name="acme/current",
                    repo_url="https://github.com/acme/current",
                    stars_period=10,
                )
            ],
            source_url="https://github.example.com/trending/python?since=daily",
            fetched_at=utcnow_iso(),
        )

    def test_writes_single_snapshot_artifact_with_diff_annotations(self) -> None:
        current = RawTrendingSnapshot(
            entries=[
                RawTrendingEntry(repo_full_name="acme/current", rank=1),
                RawTrendingEntry(repo_full_name="acme/new-hotness", rank=2),
            ],
            source_url="https://github.example.com/trending/python?since=daily",
        )
        previous = self._previous_snapshot()

        with tempfile.TemporaryDirectory() as tmpdir:
            current_path = Path(tmpdir) / "current.json"
            previous_path = Path(tmpdir) / "previous.json"
            current_path.write_text(json.dumps(current.to_dict()), encoding="utf-8")
            previous_path.write_text(json.dumps(previous.to_dict()), encoding="utf-8")

            payload = _run_script(
                PACKAGE_DIR / "scripts" / "fetch_snapshot.py",
                "--snapshot-date", "2026-04-03",
                "--since", "daily",
                "--language", "python",
                "--current-snapshot-json", str(current_path),
                "--previous-snapshot-json", str(previous_path),
                "--print-only",
            )

        self.assertEqual(payload["snapshot_date"], "2026-04-03")
        self.assertEqual(payload["history_source"], "previous_snapshot_override")
        self.assertEqual(payload["previous_snapshot_date"], "2026-04-02")
        new_repos = [entry["repo_full_name"] for entry in payload["entries"] if entry["is_new"]]
        self.assertEqual(new_repos, ["acme/new-hotness"])
        self.assertIsNone(payload["entries"][1]["previous_stars_period"])

    def test_snapshot_includes_period_stars_for_unchanged_chart_from_legacy_history(self) -> None:
        previous = self._previous_snapshot().to_dict()
        previous["entries"][0].pop("previous_stars_period")
        previous["entries"].append({
            "rank": 2,
            "repo_full_name": "acme/unknown-stars",
            "repo_url": "https://github.com/acme/unknown-stars",
            "stars_period": 0,
        })
        current = RawTrendingSnapshot(entries=[
            RawTrendingEntry(repo_full_name="acme/current", rank=1, stars_period=37),
            RawTrendingEntry(repo_full_name="acme/unknown-stars", rank=2, stars_period=5),
        ])

        with tempfile.TemporaryDirectory() as tmpdir:
            current_path = Path(tmpdir) / "current.json"
            previous_path = Path(tmpdir) / "previous.json"
            current_path.write_text(json.dumps(current.to_dict()), encoding="utf-8")
            previous_path.write_text(json.dumps(previous), encoding="utf-8")
            payload = _run_script(
                PACKAGE_DIR / "scripts" / "fetch_snapshot.py",
                "--snapshot-date", "2026-04-03",
                "--since", "daily",
                "--language", "python",
                "--current-snapshot-json", str(current_path),
                "--previous-snapshot-json", str(previous_path),
                "--print-only",
            )

        known, unknown = TrendingSnapshot.from_dict(payload).entries
        self.assertFalse(known.is_new)
        self.assertEqual(known.rank, known.previous_rank)
        self.assertEqual(known.stars_period, 37)
        self.assertEqual(known.previous_stars_period, 10)
        self.assertFalse(unknown.is_new)
        self.assertIsNone(unknown.previous_stars_period)

    def test_supplemental_charts_keep_separate_history_and_merge_by_repo_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            def run_dir(day: str) -> Path:
                layout = init_run_layout(
                    snapshot_date=day,
                    source="github-trending",
                    since="daily",
                    language="all",
                    artifact_root=tmpdir,
                )
                return Path(layout["run_dir"])

            def fetch(day: str, language: str, names: list[str]) -> dict:
                fixture = Path(tmpdir) / "fixture.json"
                fixture.write_text(json.dumps({"entries": [
                    {"repo_full_name": name, "stars_period": 20} for name in names
                ]}), encoding="utf-8")
                return _run_script(
                    PACKAGE_DIR / "scripts" / "fetch_snapshot.py",
                    "--snapshot-date", day, "--since", "daily", "--language", language,
                    "--run-dir", str(run_dir(day)), "--current-snapshot-json", str(fixture),
                    "--no-bootstrap-history", "--allow-empty-history",
                    *(["--supplemental"] if language != "all" else []),
                )

            first = "2026-04-01"
            second = "2026-04-02"
            current = "2026-04-03"
            fetch(first, "all", ["acme/main"])
            python_first = fetch(first, "python", ["ACME/known-python"])
            fetch(second, "all", ["acme/main"])
            fetch(second, "typescript", ["acme/known-ts"])
            main = fetch(current, "all", ["acme/main"])
            python = fetch(current, "python", ["acme/known-python", "Acme/shared", "ACME/MAIN"])
            typescript = fetch(current, "typescript", ["acme/known-ts", "acme/shared", "acme/ts-only"])

            output = run_dir(current)
            merged = subprocess.run(
                [sys.executable, "-m", "src.scripts.merge_snapshot_candidates",
                 "--primary", str(output / "snapshot.json"), str(output / "snapshot.python.json"),
                 str(output / "snapshot.typescript.json")],
                cwd=REPO_ROOT, capture_output=True, text=True, check=True,
            )
            self.assertEqual(json.loads((output / "snapshot.json").read_text()), main)

        self.assertEqual(python_first["history_source"], "first_run")
        self.assertEqual(python["previous_snapshot_date"], first)
        self.assertEqual(typescript["previous_snapshot_date"], second)
        self.assertFalse(python["entries"][0]["is_new"])
        self.assertFalse(typescript["entries"][0]["is_new"])
        self.assertEqual(json.loads(merged.stdout), [
            {"repo_full_name": "Acme/shared", "language": "python", "rank": 2, "stars_period": 20},
            {"repo_full_name": "acme/ts-only", "language": "typescript", "rank": 3, "stars_period": 20},
        ])

    def test_persists_to_run_dir_when_env_is_set(self) -> None:
        current = RawTrendingSnapshot(
            entries=[RawTrendingEntry(repo_full_name="acme/new-hotness", rank=1)],
            source_url="https://github.example.com/trending/python?since=daily",
        )
        previous = self._previous_snapshot()

        with tempfile.TemporaryDirectory() as tmpdir:
            init_payload = _run_script(
                PACKAGE_DIR / "scripts" / "init_run.py",
                "--language", "python",
                "--artifact-root", tmpdir,
            )
            current_path = Path(tmpdir) / "current.json"
            previous_path = Path(tmpdir) / "previous.json"
            current_path.write_text(json.dumps(current.to_dict()), encoding="utf-8")
            previous_path.write_text(json.dumps(previous.to_dict()), encoding="utf-8")

            payload = _run_script(
                PACKAGE_DIR / "scripts" / "fetch_snapshot.py",
                "--snapshot-date", "2026-04-03",
                "--since", "daily",
                "--language", "python",
                "--current-snapshot-json", str(current_path),
                "--previous-snapshot-json", str(previous_path),
                env_overrides={"DEEPTREND_RUN_DIR": init_payload["run_dir"]},
            )
            snapshot_path = Path(init_payload["run_dir"]) / "snapshot.json"
            self.assertTrue(snapshot_path.is_file())
            self.assertEqual(json.loads(snapshot_path.read_text(encoding="utf-8")), payload)

    def test_discovers_previous_run_snapshot_from_run_history(self) -> None:
        current = RawTrendingSnapshot(
            entries=[
                RawTrendingEntry(repo_full_name="acme/current", rank=1),
                RawTrendingEntry(repo_full_name="acme/new-hotness", rank=2),
            ],
            source_url="https://github.example.com/trending/python?since=daily",
        )
        previous = self._previous_snapshot()

        with tempfile.TemporaryDirectory() as tmpdir:
            previous_run = init_run_layout(
                snapshot_date="2026-04-02",
                source="github-trending",
                since="daily",
                language="python",
                artifact_root=tmpdir,
            )
            (Path(previous_run["run_dir"]) / "snapshot.json").write_text(
                json.dumps(previous.to_dict()), encoding="utf-8"
            )
            current_run = init_run_layout(
                snapshot_date="2026-04-03",
                source="github-trending",
                since="daily",
                language="python",
                artifact_root=tmpdir,
            )
            current_path = Path(tmpdir) / "current.json"
            current_path.write_text(json.dumps(current.to_dict()), encoding="utf-8")

            payload = _run_script(
                PACKAGE_DIR / "scripts" / "fetch_snapshot.py",
                "--snapshot-date", "2026-04-03",
                "--since", "daily",
                "--language", "python",
                "--artifact-root", tmpdir,
                "--current-snapshot-json", str(current_path),
                "--run-dir", current_run["run_dir"],
            )

        self.assertEqual(payload["history_source"], "previous_run")
        self.assertEqual(payload["previous_snapshot_date"], "2026-04-02")
        new_names = [entry["repo_full_name"] for entry in payload["entries"] if entry["is_new"]]
        self.assertEqual(new_names, ["acme/new-hotness"])

    def test_fails_when_history_unavailable(self) -> None:
        current = RawTrendingSnapshot(
            entries=[RawTrendingEntry(repo_full_name="acme/new-hotness", rank=1)],
            source_url="https://github.example.com/trending/python?since=daily",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            current_path = Path(tmpdir) / "current.json"
            current_path.write_text(json.dumps(current.to_dict()), encoding="utf-8")
            env = os.environ.copy()
            env["PYTHONPATH"] = str(REPO_ROOT)
            result = subprocess.run(
                [
                    sys.executable,
                    str(PACKAGE_DIR / "scripts" / "fetch_snapshot.py"),
                    "--snapshot-date", "2026-04-03",
                    "--since", "daily",
                    "--language", "python",
                    "--no-bootstrap-history",
                    "--current-snapshot-json", str(current_path),
                    "--print-only",
                ],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("fetch_snapshot failed:", result.stderr)
        self.assertIn("previous snapshot is required", result.stderr)

    def test_refuses_when_no_output_destination(self) -> None:
        current = RawTrendingSnapshot(
            entries=[RawTrendingEntry(repo_full_name="acme/new-hotness", rank=1)],
            source_url="https://github.example.com/trending/python?since=daily",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            current_path = Path(tmpdir) / "current.json"
            current_path.write_text(json.dumps(current.to_dict()), encoding="utf-8")
            env = os.environ.copy()
            env["PYTHONPATH"] = str(REPO_ROOT)
            env.pop("DEEPTREND_RUN_DIR", None)
            result = subprocess.run(
                [
                    sys.executable,
                    str(PACKAGE_DIR / "scripts" / "fetch_snapshot.py"),
                    "--snapshot-date", "2026-04-03",
                    "--since", "daily",
                    "--language", "python",
                    "--current-snapshot-json", str(current_path),
                    "--no-bootstrap-history",
                    "--allow-empty-history",
                ],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no output destination", result.stderr)

    def test_allow_empty_history_marks_first_run(self) -> None:
        current = RawTrendingSnapshot(
            entries=[
                RawTrendingEntry(repo_full_name="acme/new-hotness", rank=1),
                RawTrendingEntry(repo_full_name="acme/another", rank=2),
            ],
            source_url="https://github.example.com/trending/python?since=daily",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            current_path = Path(tmpdir) / "current.json"
            current_path.write_text(json.dumps(current.to_dict()), encoding="utf-8")

            payload = _run_script(
                PACKAGE_DIR / "scripts" / "fetch_snapshot.py",
                "--snapshot-date", "2026-04-03",
                "--since", "daily",
                "--language", "python",
                "--no-bootstrap-history",
                "--allow-empty-history",
                "--current-snapshot-json", str(current_path),
                "--print-only",
            )

        self.assertEqual(payload["history_source"], "first_run")
        self.assertIsNone(payload["previous_snapshot_date"])
        self.assertTrue(all(entry["is_new"] for entry in payload["entries"]))
        self.assertTrue(all(entry["previous_rank"] is None for entry in payload["entries"]))


class FetchRepoContextScriptTests(unittest.TestCase):
    def _resources(self) -> RawRepoResources:
        return RawRepoResources(
            metadata=RawRepoMetadata(
                repo_full_name="acme/agent-kit",
                repo_url="https://github.com/acme/agent-kit",
                description="Agent orchestration toolkit.",
                primary_language="Python",
                stars_total=1200,
                topics=["ai", "agent", "workflow"],
                homepage_url="https://acme.dev/agent-kit",
            ),
            readme="# Agent Kit\n\nToolkit.",
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

    def test_normalizes_resources_into_repo_context(self) -> None:
        resources = self._resources()
        with tempfile.TemporaryDirectory() as tmpdir:
            resources_path = Path(tmpdir) / "resources.json"
            resources_path.write_text(json.dumps(resources.to_dict()), encoding="utf-8")
            output_path = Path(tmpdir) / "context.json"
            payload = _run_script(
                PACKAGE_DIR / "scripts" / "fetch_repo_context.py",
                "--repo-full-name", "acme/agent-kit",
                "--repo-resources-json", str(resources_path),
                "--output-path", str(output_path),
            )
            self.assertEqual(payload["repo_full_name"], "acme/agent-kit")
            self.assertEqual(payload["output_path"], str(output_path))
            data = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertEqual(data["primary_language"], "Python")
        self.assertEqual(data["tag_names"], ["v1.0.0"])
        self.assertEqual(data["topics"], ["ai", "agent", "workflow"])

    def test_persists_under_run_dir_with_canonical_filename(self) -> None:
        resources = self._resources()
        with tempfile.TemporaryDirectory() as tmpdir:
            init_payload = _run_script(
                PACKAGE_DIR / "scripts" / "init_run.py",
                "--artifact-root", tmpdir,
            )
            resources_path = Path(tmpdir) / "resources.json"
            resources_path.write_text(json.dumps(resources.to_dict()), encoding="utf-8")
            payload = _run_script(
                PACKAGE_DIR / "scripts" / "fetch_repo_context.py",
                "--repo-full-name", "acme/agent-kit",
                "--repo-resources-json", str(resources_path),
                env_overrides={"DEEPTREND_RUN_DIR": init_payload["run_dir"]},
            )
            expected = Path(init_payload["run_dir"]) / "repo" / "acme__agent-kit.context.json"
            self.assertEqual(payload["output_path"], str(expected))
            self.assertTrue(expected.is_file())

    def test_truncates_long_readme_and_release_notes(self) -> None:
        long_readme = "# Title\n\n" + "x" * 5000
        long_notes = "Release notes: " + "y" * 3000
        resources = RawRepoResources(
            metadata=RawRepoMetadata(
                repo_full_name="acme/agent-kit",
                repo_url="https://github.com/acme/agent-kit",
                description="Agent orchestration toolkit.",
                primary_language="Python",
                topics=["ai"],
            ),
            readme=long_readme,
            releases=[RawRepoRelease(title="v1.0.0", notes=long_notes, published_at="2026-04-01T00:00:00Z")],
            last_commit=RawCommitInfo(sha="abc123"),
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            resources_path = Path(tmpdir) / "resources.json"
            resources_path.write_text(json.dumps(resources.to_dict()), encoding="utf-8")
            output_path = Path(tmpdir) / "context.json"
            _run_script(
                PACKAGE_DIR / "scripts" / "fetch_repo_context.py",
                "--repo-full-name", "acme/agent-kit",
                "--repo-resources-json", str(resources_path),
                "--output-path", str(output_path),
                "--readme-limit", "100",
                "--release-notes-limit", "50",
            )
            data = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertTrue(data["readme"].endswith("\n\n[truncated]"))
        self.assertTrue(data["release_notes"].endswith("\n\n[truncated]"))


class ModelRoundTripTests(unittest.TestCase):
    def test_trend_run_round_trips(self) -> None:
        snapshot = TrendingSnapshot(
            snapshot_date="2026-04-03",
            since="daily",
            language="python",
            source="github-trending",
            entries=[
                TrendingEntry(
                    rank=1,
                    repo_full_name="acme/agent-kit",
                    repo_url="https://github.com/acme/agent-kit",
                    stars_period=42,
                    is_new=True,
                )
            ],
            source_url="https://github.example.com/trending/python?since=daily",
            previous_snapshot_date="2026-04-02",
            history_source="previous_run",
            fetched_at=utcnow_iso(),
        )
        run = TrendRun(
            run_id="2026-04-03__github-trending-daily-python",
            run_dir="/tmp/run",
            snapshot=snapshot,
            analyses=[
                RepoAnalysis(
                    repo_full_name="acme/agent-kit",
                    disposition="adopt",
                    relevance="relevant",
                    summary="Agent orchestration toolkit.",
                    why="Directly targets agent workflow orchestration.",
                    analysis_md="/tmp/run/repo/acme__agent-kit.analysis.md",
                )
            ],
            report=TrendReport(
                generated_at=utcnow_iso(),
                summary="One adopted, none skipped.",
                markdown="# DeepTrend 趋势报告\n",
                statistics={"screened": 1, "adopted": 1, "tracked": 0, "skipped": 0, "new_in_diff": 1},
            ),
            delivery=Delivery(
                channel="wecom",
                status="success",
                summary="wecom: digest + attachment sent",
                sent_at=utcnow_iso(),
            ),
        )
        round_tripped = TrendRun.from_dict(run.to_dict())
        self.assertEqual(round_tripped.snapshot.entries[0].is_new, True)
        self.assertEqual(round_tripped.analyses[0].disposition, "adopt")
        self.assertEqual(round_tripped.report.statistics["adopted"], 1)
        self.assertIsNotNone(round_tripped.delivery)
        self.assertEqual(round_tripped.delivery.status, "success")


class DeliveryHelperTests(unittest.TestCase):
    def test_write_run_result_preserves_report_and_candidates_when_updating_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "2026-04-03__github-trending-daily-all"
            run_dir.mkdir()
            snapshot = TrendingSnapshot(
                snapshot_date="2026-04-03", since="daily", language="all", source="github-trending", entries=[],
            )
            (run_dir / "snapshot.json").write_text(json.dumps(snapshot.to_dict()), encoding="utf-8")
            report = "# Report\n"
            (run_dir / "report.md").write_text(report, encoding="utf-8")
            command = [sys.executable, "-m", "src.scripts.write_run_result", "--run-dir", str(run_dir)]
            candidate = {"repo_full_name": "acme/agent-kit", "language": "python", "rank": 2, "stars_period": 10}
            subprocess.run(command, cwd=REPO_ROOT, check=True, text=True, input=json.dumps({
                "summary": "Supplemental run", "statistics": {"new_in_diff": 0, "supplemental_new": 1},
                "analyses": [], "supplemental_candidates": [candidate],
            }))
            result = run_dir / "result.json"
            before = TrendRun.from_dict(json.loads(result.read_text(encoding="utf-8")))
            subprocess.run([*command, "--delivery"], cwd=REPO_ROOT, check=True, text=True,
                           input=json.dumps({"channel": "wecom", "status": "skipped"}))
            after = TrendRun.from_dict(json.loads(result.read_text(encoding="utf-8")))

        self.assertIsNone(before.delivery)
        self.assertEqual(after.delivery.status, "skipped")
        self.assertEqual(after.run_id, run_dir.name)
        self.assertEqual(after.report.markdown, report)
        self.assertEqual(after.report, before.report)
        self.assertEqual(after.snapshot, snapshot)
        self.assertEqual(after.supplemental_candidates[0].to_dict(), candidate)

    def test_report_attachment_filename_uses_run_dir_basename(self) -> None:
        run_dir = Path("/tmp/runs/2026-04-03__github-trending-daily-python")
        self.assertEqual(report_attachment_filename(run_dir), "2026-04-03__github-trending-daily-python.md")


class SendWeComScriptTests(unittest.TestCase):
    def test_dry_run_emits_skipped_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            attachment = Path(tmpdir) / "report.md"
            attachment.write_text("# DeepTrend 趋势报告\n", encoding="utf-8")
            payload = _run_script(
                PACKAGE_DIR / "scripts" / "send_wecom.py",
                "--summary-text", "# DeepTrend 概要\n- acme/agent-kit：详见附件。",
                "--attachment-path", str(attachment),
                "--attachment-filename", "2026-04-03__github-trending-daily-python.md",
                "--dry-run",
            )
        delivery = Delivery.from_dict(payload)
        self.assertEqual(delivery.channel, "wecom")
        self.assertEqual(delivery.status, "skipped")
        self.assertIn("dry-run", delivery.summary)

    def test_rejects_invalid_attachment_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            attachment = Path(tmpdir) / "report.md"
            attachment.write_text("# DeepTrend 趋势报告\n", encoding="utf-8")
            env = os.environ.copy()
            env["PYTHONPATH"] = str(REPO_ROOT)
            result = subprocess.run(
                [
                    sys.executable,
                    str(PACKAGE_DIR / "scripts" / "send_wecom.py"),
                    "--summary-text", "# DeepTrend 概要",
                    "--attachment-path", str(attachment),
                    "--attachment-filename", "../report.md",
                    "--dry-run",
                ],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("plain basename", result.stderr)

    def test_rejects_oversized_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            attachment = Path(tmpdir) / "report.md"
            attachment.write_text("# DeepTrend 趋势报告\n", encoding="utf-8")
            env = os.environ.copy()
            env["PYTHONPATH"] = str(REPO_ROOT)
            result = subprocess.run(
                [
                    sys.executable,
                    str(PACKAGE_DIR / "scripts" / "send_wecom.py"),
                    "--summary-text", "x" * 2050,
                    "--attachment-path", str(attachment),
                    "--dry-run",
                ],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("WeCom summary exceeds 2048 characters", result.stderr)


if __name__ == "__main__":
    unittest.main()
