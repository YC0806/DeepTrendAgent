"""Render the report and bounded digest from the same completed decisions."""
from __future__ import annotations

from pathlib import Path
import re

from ..models import TrendReport, utcnow_iso
from .delivery import WECOM_DIGEST_CHAR_LIMIT

SKILLS = Path(__file__).resolve().parents[2] / ".opencode/skills"
REPORT_TEMPLATE = SKILLS / "trend-run/assets/report-template.md"
DIGEST_TEMPLATE = SKILLS / "trend-deliver-wecom/assets/digest-template.md"

ZH = dict(title="DeepTrend 趋势报告", digest_title="DeepTrend 概要", overview="执行摘要", period="周期",
          language_label="语言", source_label="来源", date_label="快照日期", new="新纳入跟踪仓库",
          updated="持续跟踪仓库", skipped="不相关或暂缓仓库", stats_title="运行统计", screened="已筛选",
          adopted="新纳入跟踪", tracked="持续跟踪", deferred="不相关或暂缓", errors="检查失败",
          entries="主榜新上榜", supplement="补榜候选", moves="在榜仓库变化", rank="排名", stars="周期新增 Star",
          missing="补榜抓取失败", empty="无", highlights="重点仓库", discoveries="补充发现", daily=" 日榜",
          core="核心", adjacent="相关", more="其余重点仓库详见附件。", no_items="本期无重点仓库，详见附件。",
          static="可比指标持平", unknown="缺少可比数据")
EN = dict(title="DeepTrend trending report", digest_title="DeepTrend digest", overview="Executive summary",
          period="Period", language_label="Language", source_label="Source", date_label="Snapshot date",
          new="Newly adopted repositories", updated="Continuously tracked repositories",
          skipped="Deferred repositories", stats_title="Run statistics", screened="Screened", adopted="Adopted",
          tracked="Tracked", deferred="Deferred", errors="Failed checks", entries="New main chart entries",
          supplement="Supplemental candidates", moves="Chart changes", rank="Rank", stars="Stars this period",
          missing="Unavailable charts", empty="None", highlights="Highlights", discoveries="Supplemental discoveries",
          daily=" daily", core="Core", adjacent="Related", more="See the attachment for other highlights.",
          no_items="No highlights this period. See the attachment.", static="Comparable metrics unchanged",
          unknown="No comparable data")


def chart_moves(snapshot, words):
    moves = []
    comparable = False
    for entry in snapshot.entries:
        if entry.previous_rank is None:
            continue
        comparable = True
        rank = entry.previous_rank - entry.rank
        stars = 0
        parts = []
        if rank:
            parts.append(f"{words['rank']} {entry.previous_rank} → {entry.rank}")
        if entry.stars_period and entry.previous_stars_period:
            stars = entry.stars_period - entry.previous_stars_period
            if stars:
                parts.append(f"{words['stars']} {entry.previous_stars_period} → {entry.stars_period}")
        if parts:
            moves.append((-abs(rank), -abs(stars), entry.rank, f"- {entry.repo_full_name} · " + " · ".join(parts)))
    return [item[-1] for item in sorted(moves)[:3]] or [words["static" if comparable else "unknown"]]


def fill_template(template, values):
    body = template.split("<!--", 1)[0]
    filled = re.sub(r"{{\s*(\w+)\s*}}", lambda match: str(values[match[1]]), body)
    return re.sub(r"\n{3,}", "\n\n", filled).strip()


def format_stars(value):
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}".removesuffix(".0") + "M"
    if value >= 10_000:
        return f"{round(value / 1000)}k"
    if value >= 1000:
        return f"{value / 1000:.1f}".removesuffix(".0") + "k"
    return str(value)


def render(snapshot, analyses, stats, unavailable, words, charts=(), *, editorial=None, stars_total=None):
    labels = {f"label_{key}": value for key, value in words.items()}
    base = dict(labels, since=snapshot.since, language=snapshot.language, source=snapshot.source,
                snapshot_date=snapshot.snapshot_date)
    summary = editorial["summary"] if editorial else " · ".join(
        f"{words[key]} {stats[count]}" for key, count in (("entries", "new_in_diff"), ("screened", "screened")))
    if unavailable:
        summary += "\n\n" + words["missing"] + " · " + ", ".join(unavailable)

    positions = {(chart.language, e.repo_full_name.casefold()): e for chart in (snapshot, *charts) for e in chart.entries}
    sections = {"adopt": [], "tracked": [], "skip": []}
    highlights, failures = [], []
    supplemental = False
    for item in analyses:
        name = item.repo_full_name
        link = f"[{name}](https://github.com/{name})"
        if item.error:
            failures.append(f"- {link} · {words['errors']}")
            continue
        copy = editorial["repositories"][name] if editorial and item.disposition != "skip" else {}
        entry = positions.get((item.chart, name.casefold()))
        segments = []
        if entry and entry.rank:
            rank = f"#{entry.rank}"
            if item.chart != snapshot.language:
                chart_name = {"python": "Python", "typescript": "TypeScript"}.get(item.chart, item.chart)
                rank = f"{chart_name}{words['daily']} {rank}"
            segments.append(rank)
        total = (stars_total or {}).get(name, 0)
        if total:
            segments.append("⭐" + format_stars(total))
        if entry and entry.stars_period:
            segments.append("+" + format_stars(entry.stars_period))
        if item.relevance in ("relevant", "adjacent"):
            segments.append(words["core" if item.relevance == "relevant" else "adjacent"])
        meta = " · ".join(segments)
        row = f"- {link}" + (f"（{meta}）" if meta else "")
        description = copy.get("report") or " ".join(filter(None, (item.summary, item.why)))
        sections[item.disposition].append(f"{row}：{description}")
        if item.disposition != "skip":
            highlights.append(f"{row}：{copy.get('digest') or item.summary}")
            supplemental |= item.chart != snapshot.language

    moves = chart_moves(snapshot, words) if not stats["new_in_diff"] else []
    changes_heading = f"## {words['moves']}"
    if snapshot.previous_snapshot_date:
        changes_heading += f" · {snapshot.previous_snapshot_date} → {snapshot.snapshot_date}"
    optional_stats = [f"- {words['supplement']}：{stats['supplemental_new']}"] if "supplemental_new" in stats else []
    if failures:
        optional_stats.append(f"- {words['errors']}：{len(failures)}")
    values = dict(base, **stats, summary=summary, chart_changes_section="\n\n".join([changes_heading, *moves]) if moves else "",
                  adopted_section="\n\n".join(sections["adopt"]) or words["empty"],
                  tracked_section="\n\n".join(sections["tracked"]) or words["empty"],
                  skipped_section="\n\n".join(sections["skip"] + failures) or words["empty"],
                  supplemental_statistics="\n".join(optional_stats))
    markdown = fill_template(REPORT_TEMPLATE.read_text(encoding="utf-8"), values) + "\n"

    title = words["discoveries" if supplemental else "highlights"]
    lines = highlights
    if not lines and moves and moves[0].startswith("- "):
        title, lines = words["moves"], moves
    template = DIGEST_TEMPLATE.read_text(encoding="utf-8")
    fitted = list(lines or ["- " + words["no_items"]])
    footer = ""
    while True:
        digest = fill_template(template, dict(base, section_title=title, items="\n".join(fitted), trim_footer=footer))
        if len(digest) <= WECOM_DIGEST_CHAR_LIMIT:
            break
        if not fitted:
            raise ValueError("WeCom digest template header exceeds the character limit")
        fitted.pop()
        footer = "- " + words["more"]
    return TrendReport(utcnow_iso(), summary, markdown, stats, generation="agent" if editorial else "template"), digest
