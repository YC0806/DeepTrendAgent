---
name: trend-analyze-one
description: Build repo context for a single trending repository, judge its relevance to the agent/LLM-infra domain, decide a disposition (tracked / adopt / skip), and write a fixed-template analysis Markdown when adopted or tracked. Returns one `RepoAnalysis` handoff.
---

# Trend Analyze One

One sub agent, one repository.

## Inputs

- `repo_full_name`: target repository (e.g. `openai/openai-python`)
- `run_dir`: active DeepTrend run directory
- `output_language`: language for the analysis Markdown (default 简体中文)

## Run Steps

1. Build the repo context: `python3 src/scripts/fetch_repo_context.py --repo-full-name <name> --run-dir <run_dir>`. This writes `<run_dir>/repo/<slug>.context.json`. Read that file. Always pass `--run-dir` explicitly — bash subprocesses do not inherit env from the parent dispatcher, so relying on `DEEPTREND_RUN_DIR` will silently drop the file.
2. Compose a 2–3 sentence description covering: (1) what the repo does and its primary use case, (2) core technical approach or distinguishing implementation detail, (3) key capabilities or integrations if space allows. Draw from README, description, and topics. Avoid generic openers like "a framework for..." and star/popularity signals.
3. Judge relevance against the focus domain (see `assets/focus-domains.md`):
   - `relevant`: directly part of agent runtime, LLM-infra, RAG, eval/observability, or agent tool ecosystem
   - `adjacent`: enabling infrastructure or upstream/downstream tooling for the above
   - `irrelevant`: outside the domain
4. Pick a disposition:
   - `adopt` for `relevant` or `adjacent` (unless evidence is too thin)
   - `skip` for `irrelevant` or for `adjacent` items with very thin evidence
   - `tracked` only if explicit tracking state for this repo was passed in (rare)
5. For `adopt` and `tracked`: write the analysis Markdown to `<run_dir>/repo/<slug>.analysis.md` following `assets/analysis-template.md`. For `skip`: do not write a Markdown file.
6. Return the `RepoAnalysis` handoff to the orchestrator.

## Analysis Depth

Default to repo-level signals (README + releases + description + topics + last commit). Only go deeper when one specific claim in the analysis Markdown needs concrete evidence:

- one targeted subtree listing via `get_git_repo_tree(repo_full_name, path=...)`
- one or two source files via `get_git_repo_file_content(repo_full_name, path=...)`

Do not browse the source tree broadly, do not study commit history, do not produce code-review-style judgments.

## Markdown Template

Every analysis Markdown follows `assets/analysis-template.md`:

- `# <repo_full_name>`
- `## 是什么`
- `## 为什么现在重要`
- `## 技术信号`
- `## 跟踪建议`

## Slug Convention

`<slug>` is `repo_full_name` with `/` replaced by `__`. Example: `langchain-ai/langgraph` → `langchain-ai__langgraph`.

## Handoff Contract

Return a single `RepoAnalysis`:

- `repo_full_name`: same as input
- `disposition`: `tracked` | `adopt` | `skip`
- `relevance`: `relevant` | `adjacent` | `irrelevant`
- `summary`: 2–3 sentences covering use case, technical approach, and key capabilities
- `why`: one or two sentences justifying the disposition
- `analysis_md`: path to the written Markdown, or null when `disposition=skip`
- `error`: null when the analysis succeeded; a short message otherwise

If `fetch_repo_context.py` fails or the context JSON is empty, return `disposition=skip`, `relevance=irrelevant`, and a non-null `error` describing the failure. Do not fabricate analysis from the repo name alone.

## Example Handoff

```
分析完成 langchain-ai/langgraph
disposition: adopt
relevance: relevant
summary: 基于有向图状态机的 LLM agent 编排框架，用节点/边描述多 agent 协作流程。内置持久化、断点续跑和并行节点执行，适用于复杂的长任务 agent pipeline。
why: 直接命中 agent runtime / multi-agent 关注点，README 与最新 release 都强调编排能力扩展。
analysis_md: <run_dir>/repo/langchain-ai__langgraph.analysis.md
```
