"""OpenCode batch boundary. The model supplies text, the pipeline owns all I/O."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from ..models import RepoAnalysis, RepoContext

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / ".opencode/skills/trend-analyze-one"


def ask_json(prompt: str) -> dict:
    args = [os.environ.get("OPENCODE_BIN") or "opencode", "run", "--dir", str(ROOT), "--format", "json"]
    for flag, key in [("-m", "OPENCODE_MODEL"), ("--agent", "OPENCODE_AGENT")]:
        if os.environ.get(key):
            args.extend([flag, os.environ[key]])
    env = {**os.environ, "OPENCODE_PERMISSION": '{"*":"deny"}'}
    for key in ("GITHUB_TOKEN", "GH_TOKEN", "WECOM_WEBHOOK_KEY"):
        env.pop(key, None)
    try:
        response = subprocess.run(args, input=prompt, env=env, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        raise RuntimeError("OpenCode timed out after 300 seconds") from None
    if response.returncode:
        raise RuntimeError(f"OpenCode exited with status {response.returncode}")
    answer = []
    for line in response.stdout.splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if not isinstance(event, dict):
            raise ValueError("Invalid OpenCode event")
        if event.get("type") == "error":
            error = event.get("error") or {}
            raise RuntimeError(f"OpenCode error: {error.get('name', 'unknown')}")
        if event.get("type") == "text":
            part = event.get("part")
            if not isinstance(part, dict) or not isinstance(part.get("text"), str):
                raise ValueError("Invalid OpenCode text event")
            answer.append(part["text"])
    value = json.loads("".join(answer).strip().removeprefix("```json").removesuffix("```").strip())
    if not isinstance(value, dict):
        raise ValueError("Expected one JSON object from OpenCode")
    return value


def analyze(context: RepoContext, name: str, action: str, changes: dict, language: str,
            chart: str, md_path: Path) -> RepoAnalysis:
    instructions = "\n".join(
        (SKILL / file).read_text(encoding="utf-8")
        for file in ("SKILL.md", "assets/focus-domains.md", "assets/analysis-template.md")
    )
    task = dict(repo_full_name=name, action=action, changes=changes, context=context.to_dict(),
                output_language=language, chart=chart)
    prompt = "Evaluate the following single repository task.\n" + instructions + "\nInput data:\n" + json.dumps(task, ensure_ascii=False)
    for attempt in range(2):
        try:
            data = ask_json(prompt)
            kept = "adopt" if action == "new_entry" else "tracked"
            disposition = data.get("disposition")
            relevance = data.get("relevance")
            if (data.get("repo_full_name") != name or disposition not in (kept, "skip")
                    or relevance not in ("relevant", "adjacent", "irrelevant")
                    or (relevance == "irrelevant" and disposition != "skip")):
                raise ValueError("Invalid repository, disposition or relevance in agent response")
            for field in ("summary", "why"):
                if not isinstance(data.get(field), str) or not data[field].strip():
                    raise ValueError(f"Missing {field} in agent response")
            if disposition == kept:
                if not isinstance(data.get("markdown"), str) or not data["markdown"].strip():
                    raise ValueError("Missing analysis Markdown")
                md_path.write_text(data["markdown"], encoding="utf-8")
            return RepoAnalysis(name, disposition, relevance, data["summary"], data["why"],
                                str(md_path) if disposition == kept else None,
                                action=action, chart=chart, changes=changes)
        except (ValueError, KeyError, RuntimeError):
            if attempt:
                raise
