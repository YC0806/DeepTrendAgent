import json
import os
import subprocess
import sys
import threading
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from src.models import RepoContext, TrendingEntry, TrendingSnapshot
from src.scripts.run_pipeline import update_signals


def test_pipeline_with_legacy_history_and_two_charts(tmp_path):
    paths = []
    charts = {"all": ["demo/old", "demo/steady", "demo/baseline"],
              "python": ["demo/new", "demo/old"], "typescript": ["Demo/New"]}
    class GitHub(BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?")[0]
            paths.append(path)
            if path.startswith("/trending"):
                names = charts[path.removeprefix("/trending").strip("/") or "all"]
                body = "".join(f'<article class="Box-row"><h2><a href="/{name}">project</a></h2></article>'
                               for name in names)
            else:
                _, _, owner, repo, *endpoint = path.split("/")
                assert owner == "demo"
                data = {"full_name": f"{owner}/{repo}", "default_branch": "main"}
                if endpoint == ["commits"]:
                    data = [{"sha": "current", "commit": {"message": "New streaming API"}}]
                elif endpoint in (["releases"], ["tags"]):
                    data = []
                body = json.dumps(data)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *args):
            pass

    yesterday = (date.today() - timedelta(days=1)).isoformat()
    slug = "__github-trending-daily-all"
    runs = tmp_path / "runs"
    past = runs / (yesterday + slug)
    (past / "repo").mkdir(parents=True)
    snapshot = TrendingSnapshot(yesterday, "daily", "all", "github-trending", [
        TrendingEntry(rank, name, f"https://github.com/{name}") for rank, name in
        enumerate([*charts["all"], "demo/offchart"], 1)])
    (past / "snapshot.json").write_text(json.dumps(snapshot.to_dict()))
    (past / "result.json").write_text('{"analyses":[]}')
    for name, sha in [("old", "previous"), ("steady", "current"), ("offchart", "offchart")]:
        (past / "repo" / f"demo__{name}.context.json").write_text(json.dumps({
            "repo_full_name": f"demo/{name}", "repo_url": f"https://github.com/demo/{name}", "last_commit_hash": sha,
        }))
    opencode = tmp_path / "opencode"
    opencode.write_text("""#!/usr/bin/env python3
import sys, os, json
from pathlib import Path
task = json.loads(sys.stdin.read().split('Input data:\\n')[1])
if 'repositories' in task:
    result = dict(summary="编辑撰写的导语", repositories={name: dict(report="正文", digest="群摘要") for name in task["repositories"]})
    print(json.dumps({'type':'text','part':{'text':json.dumps(result)}}))
    sys.exit(0)
name = task['repo_full_name']
assert 'WECOM_WEBHOOK_KEY' not in os.environ
assert 'GITHUB_TOKEN' not in os.environ
assert task['output_language'] == '简体中文'
attempt = Path(os.environ['TEST_DIR']) / name.replace('/', '_')
with attempt.open('a') as f:
    f.write('1')
result = dict(repo_full_name=name, disposition='adopt' if task['action']=='new_entry' else 'tracked',
              relevance='relevant', summary='有可核实的工程变化。', why='release / commit', markdown='# Detail')
if name == 'demo/old' and attempt.read_text() == '1':
    result['repo_full_name'] = 'wrong/repo'
print(json.dumps({'type':'text','part':{'text':json.dumps(result)}}))
""")
    opencode.chmod(0o755)
    with ThreadingHTTPServer(("127.0.0.1", 0), GitHub) as server:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        base = f"http://127.0.0.1:{server.server_port}"
        env = {**os.environ, "GITHUB_BASE_URL": base, "GITHUB_API_BASE_URL": base,
               "GITHUB_PROXY_URL": "", "OPENCODE_BIN": str(opencode), "TEST_DIR": str(tmp_path),
               "WECOM_WEBHOOK_KEY": "", "GITHUB_TOKEN": "test-token", "no_proxy": "127.0.0.1"}
        cmd = [sys.executable, "-m", "src.scripts.run_pipeline", "--artifact-root", str(tmp_path), "--dry-run"]
        try:
            subprocess.run(cmd, env=env, check=True, capture_output=True, text=True, timeout=30)
            calls = len(paths)
            subprocess.run(cmd, env=env, check=True, capture_output=True, text=True, timeout=30)
            assert len(paths) == calls
        finally:
            server.shutdown()
            worker.join()

    run = runs / (date.today().isoformat() + slug)
    result = json.loads((run / "result.json").read_text())
    assert result["delivery"]["status"] == "skipped"
    assert result["report"]["statistics"] == dict(adopted=1, tracked=1, skipped=0, screened=2, errors=0,
                                                 new_in_diff=0, supplemental_new=1, unchanged=1, baselines=1)
    assert [(a["repo_full_name"], a["action"]) for a in result["analyses"]] == [
        ("demo/old", "repo_update"), ("demo/new", "new_entry")]
    assert result["analyses"][0]["changes"] == {"last_commit_hash": ["previous", "current"]}
    assert (tmp_path / "demo_old").read_text() == "11"
    assert [p for p in paths if "/offchart" in p] == []
    assert sorted(p for p in paths if "/steady" in p) == ["/repos/demo/steady/commits", "/repos/demo/steady/releases"]
    assert (run / "repo/demo__baseline.context.json").exists()
    report = (run / "report.md").read_text()
    assert result["report"]["generation"] == "agent"
    assert result["report"]["summary"] == "编辑撰写的导语"
    assert (run / "wecom.digest.md").read_text().endswith("群摘要")
    assert report == result["report"]["markdown"]
    assert "## 新纳入跟踪仓库" in report and "## 持续跟踪仓库" in report and "Python 日榜 #1" in report


def test_first_release_is_evidence_and_stars_are_not():
    before = RepoContext("demo/repo", "url", stars_total=100)
    after = RepoContext("demo/repo", "url", stars_total=120)
    assert not update_signals(before, after)
    after.latest_release_title = "v1"
    assert update_signals(before, after) == {"latest_release_title": [None, "v1"]}


def test_main_new_entries_suppress_fallback_and_agent_errors_are_separate(tmp_path, monkeypatch):
    from argparse import Namespace
    from src.models import RepoAnalysis
    from src.scripts import run_pipeline

    run_dir = tmp_path / "2026-11-24__github-trending-daily-all"
    run_dir.mkdir()
    primary = TrendingSnapshot("2026-11-24", "daily", "all", "github-trending", [
        TrendingEntry(1, "demo/new", "url", is_new=True), TrendingEntry(2, "demo/old", "url", previous_rank=1)])
    calls = []

    def fetch(run_dir, date, since, language):
        calls.append(language)
        return primary

    def inspect(job, **kwargs):
        if job[2]:
            return "errors", RepoAnalysis(job[0], "skip", "irrelevant", "", "", error="invalid response",
                                          action="new_entry", chart=job[1])
        return "baselines", None

    monkeypatch.setattr(run_pipeline, "fetch_chart", fetch)
    monkeypatch.setattr(run_pipeline, "inspect_repo", inspect)
    from src.scripts import _report_editor
    monkeypatch.setattr(_report_editor, "ask_json", lambda _: dict(summary="No highlights.", repositories={}))
    args = Namespace(date=primary.snapshot_date, since="daily", language="all", workers=2, output_language="en")
    run = run_pipeline.build_run(run_dir, args)
    assert calls == ["all"]
    assert run.report.statistics["errors"] == 1
    assert run.report.statistics["skipped"] == 0
    assert "Failed checks" in run.report.markdown


def test_older_valid_context_used_after_failed_update(tmp_path):
    from src.scripts.run_pipeline import historical_contexts

    suffix = "__github-trending-daily-all"
    for day, failed in [("2026-11-22", False), ("2026-11-23", True)]:
        folder = tmp_path / (day + suffix)
        (folder / "repo").mkdir(parents=True)
        (folder / "result.json").write_text(json.dumps({"analyses": [
            {"repo_full_name": "demo/repo", "error": "model timeout" if failed else None}]}))
        (folder / "repo/demo__Repo.context.json").write_text(json.dumps(
            dict(repo_full_name="demo/Repo", repo_url="url", last_commit_hash=day)))
    history = historical_contexts(tmp_path / ("2026-11-24" + suffix), ["demo/REPO"])
    assert history["demo__repo"].last_commit_hash == "2026-11-22"


def test_editor_slots_preserve_templates_on_retry_and_fallback(tmp_path, monkeypatch):
    from src.models import RepoAnalysis
    from src.scripts import _report_editor as editor
    from src.tools.report import ZH

    snapshot = TrendingSnapshot("2026-11-25", "daily", "all", "github-trending", [
        TrendingEntry(1, "demo/repo", "url", 25, True)])
    analyses = [RepoAnalysis("demo/repo", "adopt", "relevant", "项目用途。", "采纳理由。", chart="all")]
    stats = dict(new_in_diff=1, screened=1, adopted=1, tracked=0, skipped=0)
    calls = []

    def respond(prompt):
        calls.append(prompt)
        summary = "## 擅自改栏目" if len(calls) == 1 else "今天的发现。"
        return dict(summary=summary, repositories={"demo/repo": dict(report="正文解读。", digest="群内短评。")})

    monkeypatch.setattr(editor, "ask_json", respond)
    r, d = editor.edit_report(snapshot, analyses, stats, [], ZH, language="简体中文", run_dir=tmp_path)
    assert len(calls) == 2 and "plain paragraphs" in calls[1]
    headings = [line for line in r.markdown.splitlines() if line.startswith("#")]
    assert headings == ["# DeepTrend 趋势报告", "## 执行摘要", "## 新纳入跟踪仓库", "## 持续跟踪仓库",
                        "## 不相关或暂缓仓库", "## 运行统计"]
    assert r.generation == "agent" and "正文解读。" in r.markdown and r.summary == "今天的发现。"
    assert d == ("# DeepTrend 概要\n> 2026-11-25 · daily/all\n\n## 重点仓库\n"
                 "- [demo/repo](https://github.com/demo/repo)（#1 · +25 · 核心）：群内短评。")

    monkeypatch.setattr(editor, "ask_json", lambda _: {"summary": "bad", "repositories": {}})
    r, d = editor.edit_report(snapshot, analyses, stats, [], ZH, language="简体中文", run_dir=tmp_path)
    assert r.generation == "template" and "项目用途。" in d and d.startswith("# DeepTrend 概要\n>")


def test_quiet_day_and_long_digest_follow_template():
    from src.models import RepoAnalysis
    from src.tools.report import ZH, render

    snapshot = TrendingSnapshot("2026-11-25", "daily", "all", "github-trending", [
        TrendingEntry(1, "demo/repo", "url", 25, previous_rank=2)])
    stats = dict(new_in_diff=0, supplemental_new=0, screened=0, adopted=0, tracked=0, skipped=0)
    r, d = render(snapshot, [], stats, ["typescript"], ZH)
    assert "## 在榜仓库变化" in r.markdown and "## 在榜仓库变化\n- demo/repo" in d
    assert "- 补榜候选：0" in r.markdown and "typescript" in r.summary
    analyses = [RepoAnalysis(f"demo/r{i}", "tracked", "relevant", "变化。" * 170, "", chart="all") for i in range(8)]
    _, d = render(snapshot, analyses, stats, [], ZH)
    assert len(d) <= 2048 and d.endswith("其余重点仓库详见附件。")
    assert d.count("变化。" * 170) == d.count("https://github.com/")
