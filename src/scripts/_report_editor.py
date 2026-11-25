"""Commission narrative copy, then fill the report and digest templates."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from ..models import RepoAnalysis, TrendingSnapshot
from ..tools.report import chart_moves, render
from ._cli_common import repo_slug_from_full_name
from ._repo_agent import ROOT, ask_json


def _paragraph(value):
    # Each editorial slot is prose. Keep Markdown block structure in the templates.
    if not isinstance(value, str) or not value.strip():
        raise ValueError("each prose slot must contain a nonempty paragraph")
    if re.search(r"^\s*(?:#{1,6}\s|[-*+]\s|\d+[.)]\s|>|~~~|```|<!--|<[/!a-zA-Z])", value, re.MULTILINE):
        raise ValueError("return plain paragraphs without headings, lists or markup blocks")
    return " ".join(value.split())


def edit_report(snapshot: TrendingSnapshot, analyses: list[RepoAnalysis], stats: dict,
                unavailable: list[str], words: dict, supplements=(), *, language: str, run_dir: Path):
    instructions = (ROOT / ".opencode/skills/trend-run/assets/report-editor.md").read_text(encoding="utf-8")
    kept, totals = {}, {}
    for a in analyses:
        if a.error or a.disposition == "skip":
            continue
        name = a.repo_full_name
        path = run_dir / "repo" / (repo_slug_from_full_name(name) + ".context.json")
        if path.is_file():
            totals[name] = json.loads(path.read_text(encoding="utf-8")).get("stars_total", 0)
        kept[name] = dict(action=a.action, chart=a.chart, summary=a.summary, reasoning=a.why,
                          changes=a.changes, detail=Path(a.analysis_md).read_text(encoding="utf-8") if a.analysis_md else None)
    evidence = dict(snapshot_date=snapshot.snapshot_date, period=snapshot.since, main_chart=snapshot.language,
                    output_language=language, statistics=stats, repositories=kept, unavailable_charts=unavailable,
                    chart_movements=chart_moves(snapshot, words) if not stats["new_in_diff"] else [])
    prompt = instructions + "\nInput data:\n" + json.dumps(evidence, ensure_ascii=False)
    feedback = ""
    editorial = None
    for _ in range(2):
        try:
            draft = ask_json(feedback + prompt)
            entries = draft.get("repositories")
            if not isinstance(entries, dict) or set(entries) != set(kept):
                raise ValueError("return exactly the repository keys supplied in the input")
            copy = {}
            for name, entry in entries.items():
                if not isinstance(entry, dict):
                    raise ValueError(f"missing report and digest slots for {name}")
                copy[name] = {key: _paragraph(entry.get(key)) for key in ("report", "digest")}
            editorial = dict(summary=_paragraph(draft.get("summary")), repositories=copy)
            break
        except (OSError, ValueError, RuntimeError) as exc:
            print(f"Report editor: {exc}", file=sys.stderr)
            feedback = f"Previous attempt: {exc}. Return the complete JSON object.\n"
    if editorial is None:
        print("Using completed analyses as template copy.", file=sys.stderr)
    return render(snapshot, analyses, stats, unavailable, words, supplements, editorial=editorial, stars_total=totals)
