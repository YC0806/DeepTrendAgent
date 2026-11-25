"""Run DeepTrend's fixed chart, discovery, update and delivery stages."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import fcntl
import json
import os
from pathlib import Path
from functools import partial
import re
import subprocess
import sys

from ..models import Delivery, RepoAnalysis, RepoContext, TrendingSnapshot, TrendRun
from ..provider import GitHubRepoResourcesProvider
from ..tools.github.github_diff import merge_new_entries
from ..tools.report import EN, ZH
from ._cli_common import default_snapshot_date, init_run_layout, repo_slug_from_full_name, write_json
from ._report_editor import edit_report
from ._repo_agent import analyze, ask_json, ROOT


def script(name, *args, accepted=(0,)):
    result = subprocess.run([sys.executable, "-m", f"src.scripts.{name}", *map(str, args)],
                            cwd=ROOT, capture_output=True, text=True)
    if result.returncode not in accepted:
        raise RuntimeError(f"{name}: {result.stderr.strip() or result.returncode}")
    return json.loads(result.stdout)


def fetch_chart(run_dir, date, since, language, supplemental=False):
    args = ["--run-dir", run_dir, "--since", since, "--language", language,
            "--snapshot-date", date, "--allow-empty-history"]
    if supplemental:
        args += ["--supplemental", "--no-bootstrap-history"]
    return TrendingSnapshot.from_dict(script("fetch_snapshot", *args))


def historical_contexts(run_dir: Path, names: list[str]) -> dict[str, RepoContext]:
    """Look only for today's repositories in earlier runs of this chart."""
    waiting = {repo_slug_from_full_name(name).casefold() for name in names}
    found = {}
    for past in sorted(run_dir.parent.glob("*__" + run_dir.name.split("__", 1)[1]), reverse=True):
        if not waiting:
            break
        if past.name >= run_dir.name or not (past / "result.json").is_file():
            continue
        matches = [file for file in (past / "repo").glob("*.context.json")
                   if file.name.removesuffix(".context.json").casefold() in waiting]
        if not matches:
            continue
        result = json.loads((past / "result.json").read_text(encoding="utf-8"))
        failed = {repo_slug_from_full_name(a["repo_full_name"]).casefold()
                  for a in result.get("analyses", []) if a.get("error")}
        for file in matches:
            slug = file.name.removesuffix(".context.json").casefold()
            if slug in waiting and slug not in failed:
                found[slug] = RepoContext.from_dict(json.loads(file.read_text(encoding="utf-8")))
                waiting.remove(slug)
    return found


def update_signals(previous: RepoContext, current: RepoContext) -> dict[str, list[str | None]]:
    changes = {}
    for key in ("latest_release_published_at", "latest_release_title", "last_commit_hash"):
        old, new = getattr(previous, key), getattr(current, key)
        if new and new != old and (old or key != "last_commit_hash"):
            changes[key] = [old, new]
    return changes


def inspect_repo(job, previous, run_dir, output_language):
    name, chart, is_new = job
    action = "new_entry" if is_new else "repo_update"
    slug = repo_slug_from_full_name(name)
    changes = {}
    try:
        if not re.fullmatch(r"[a-zA-Z0-9-]+/[a-zA-Z0-9_.-]+", name):
            raise ValueError("Invalid GitHub repository name")
        context_path = run_dir / "repo" / f"{slug}.context.json"
        baseline = previous.get(slug.casefold())
        if not is_new and baseline and baseline.last_commit_hash:
            api = GitHubRepoResourcesProvider()
            releases = api.fetch_repo_releases(name, limit=1)
            commit = api.fetch_last_commit(name)
            probe = RepoContext(name, baseline.repo_url, last_commit_hash=commit.sha,
                                latest_release_published_at=releases[0].published_at if releases else None,
                                latest_release_title=releases[0].title if releases else None)
            if not update_signals(baseline, probe):
                return "unchanged", None
        script("fetch_repo_context", "--repo-full-name", name, "--run-dir", run_dir)
        current = RepoContext.from_dict(json.loads(context_path.read_text(encoding="utf-8")))
        if not is_new:
            if baseline is None:
                return "baselines", None
            changes = update_signals(baseline, current)
            if not changes:
                return "unchanged", None
        analysis = analyze(current, name, action, changes, output_language, chart,
                           run_dir / "repo" / f"{slug}.analysis.md")
        return "screened", analysis
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"{name} ({action}): {exc}", file=sys.stderr)
        return "errors", RepoAnalysis(name, "skip", "irrelevant", "", "", error=str(exc),
                                      action=action, chart=chart, changes=changes)


def report_words(language):
    if language.casefold() in ("zh", "zh-cn", "简体中文", "中文", "chinese", "simplified chinese"):
        return ZH
    if language.casefold() in ("en", "en-us", "en-gb", "english", "英语", "英文"):
        return EN
    words = ask_json(f"Translate the following report labels into {language}. Keep all JSON keys and return only "
                     f"the translated JSON object.\n{json.dumps(EN)}")
    if words.keys() != EN.keys() or not all(isinstance(v, str) and v.strip() for v in words.values()):
        raise ValueError("Invalid translated report labels")
    return words


def build_run(run_dir, args):
    snapshot = fetch_chart(run_dir, args.date, args.since, args.language)
    supplements, unavailable = [], []
    primary_new = sum(entry.is_new for entry in snapshot.entries)
    fallback = args.since == "daily" and args.language == "all" and not primary_new
    if fallback:
        for language in ("python", "typescript"):
            try:
                supplements.append(fetch_chart(run_dir, args.date, args.since, language, True))
            except (RuntimeError, ValueError) as exc:
                print(f"{language}: {exc}", file=sys.stderr)
                unavailable.append(language)
    candidates = merge_new_entries(snapshot, supplements)
    jobs = {}
    for entry in snapshot.entries:
        jobs.setdefault(entry.repo_full_name.casefold(), (entry.repo_full_name, snapshot.language, entry.is_new))
    for entry in candidates:
        jobs[entry.repo_full_name.casefold()] = (entry.repo_full_name, entry.language, True)
    for chart in supplements:
        for entry in chart.entries:
            jobs.setdefault(entry.repo_full_name.casefold(), (entry.repo_full_name, chart.language, False))

    previous = historical_contexts(run_dir, [name for name, _, new in jobs.values() if not new])
    stats = dict(new_in_diff=primary_new, screened=0, adopted=0, tracked=0, skipped=0,
                 baselines=0, unchanged=0, errors=0)
    if fallback:
        stats["supplemental_new"] = len(candidates)
    analyses = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        inspect = partial(inspect_repo, previous=previous, run_dir=run_dir, output_language=args.output_language)
        for status, analysis in pool.map(inspect, jobs.values()):
            stats[status] += 1
            if analysis:
                analyses.append(analysis)
                if not analysis.error:
                    stats[{"adopt": "adopted", "tracked": "tracked", "skip": "skipped"}[analysis.disposition]] += 1
    report, digest = edit_report(snapshot, analyses, stats, unavailable, report_words(args.output_language),
                                 supplements, language=args.output_language, run_dir=run_dir)
    (run_dir / "report.md").write_text(report.markdown, encoding="utf-8")
    (run_dir / "wecom.digest.md").write_text(digest, encoding="utf-8")
    return TrendRun(run_dir.name, str(run_dir), snapshot, analyses, report, supplemental_candidates=candidates)


def publish(run, run_dir, dry_run):
    run.delivery = None
    write_result(run_dir, run)
    delivery = script("send_wecom", "--summary-path", run_dir / "wecom.digest.md",
                      "--attachment-path", run_dir / "report.md", "--attachment-filename", f"{run_dir.name}.md",
                      *(["--dry-run"] if dry_run else []), accepted=(0, 2))
    run.delivery = Delivery.from_dict(delivery)
    write_result(run_dir, run)


def write_result(run_dir, run):
    pending = run_dir / ".result.json.tmp"
    write_json(pending, run.to_dict(), pretty=True)
    pending.replace(run_dir / "result.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", choices=("daily", "weekly", "monthly"), default="daily")
    parser.add_argument("--language", default="all")
    parser.add_argument("--output-language", default="简体中文")
    parser.add_argument("--artifact-root")
    parser.add_argument("--workers", type=int, default=os.environ.get("DEEPTREND_WORKERS", "4"))
    parser.add_argument("--dry-run", action="store_true", help="Generate the report without WeCom delivery.")
    parser.add_argument("--retry-delivery", action="store_true",
                        help="Resend a saved report after an interrupted or failed delivery.")
    args = parser.parse_args()
    if args.retry_delivery and args.dry_run:
        parser.error("--retry-delivery cannot be combined with --dry-run")
    if args.workers < 1:
        parser.error("--workers must be positive")
    args.date = default_snapshot_date()
    layout = init_run_layout(snapshot_date=args.date, source="github-trending", since=args.since,
                             language=args.language, artifact_root=args.artifact_root)
    run_dir = Path(layout["run_dir"])
    with (run_dir / ".pipeline.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        result_path = run_dir / "result.json"
        if args.retry_delivery and not result_path.is_file():
            parser.error("--retry-delivery requires an existing run result")
        if result_path.exists():
            run = TrendRun.from_dict(json.loads(result_path.read_text(encoding="utf-8")))
            pending = run.delivery is None or run.delivery.status == "failed"
            if pending and not args.retry_delivery:
                parser.exit(1, f"Delivery incomplete in {result_path}; inspect WeCom and use --retry-delivery to resend.\n")
            if pending:
                run.delivery = None
        else:
            run = build_run(run_dir, args)
        if not run.delivery or (run.delivery.status == "skipped" and not args.dry_run):
            publish(run, run_dir, args.dry_run)
        print(json.dumps(dict(run_id=run.run_id, report=str(run_dir / "report.md"),
                              statistics=run.report.statistics, delivery=run.delivery.status), ensure_ascii=False))
        return int(run.delivery.status == "failed" or bool(run.report.statistics.get("errors")))


if __name__ == "__main__":
    raise SystemExit(main())
