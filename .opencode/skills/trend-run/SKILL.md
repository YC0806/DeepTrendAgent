---
name: trend-run
description: Run the end-to-end DeepTrend workflow from a single skill — fetch the GitHub trending snapshot, diff against the previous run, dispatch one `trend-analyze-one` sub agent per new repository in parallel, render the Markdown report, and deliver to WeCom. The whole `TrendRun` is owned by this skill.
---

# Trend Run

The default entrypoint for a DeepTrend run. One skill, one end-to-end flow.

## Inputs

- `since`: `daily` | `weekly` | `monthly` (default `daily`)
- `language`: GitHub trending language filter (default `all`)
- `output_language`: report and digest output language (default 简体中文)

## Run Steps

1. Initialize the run directory with `python3 src/scripts/init_run.py --since <since> --language <language>`. Capture `run_dir` from the returned JSON — you (the orchestrator) are responsible for threading it into every subsequent script call as `--run-dir <run_dir>`. Bash invocations do not share shell state, so the `DEEPTREND_RUN_*` env values printed by init_run are not auto-inherited; relying on them will silently drop artifacts.
2. Fetch the snapshot with `python3 src/scripts/fetch_snapshot.py --run-dir <run_dir> --since <since> --language <language>`. This writes `<run_dir>/snapshot.json` containing the current snapshot, diff annotations (`is_new`, `previous_rank`, `previous_stars_period`), `previous_snapshot_date`, and `history_source`. Failure handling:
   - If stderr contains `previous snapshot is required for diff` or `no historical snapshot was found`, this is the first-run / archive-gap case (no prior run for this `since`/`language`, and the archive repo has no entry for the date). Re-run the same command with `--allow-empty-history` appended. The script will then mark every entry `is_new=true` and set `history_source="first_run"`. Do not edit the script.
   - For any other error (network, auth, normalization), stop and surface the printed stderr verbatim. `--allow-empty-history` only covers "no data available," not fetch failures.
3. Read `<run_dir>/snapshot.json` and select entries with `is_new == true` in chart order. Initialize `supplemental_candidates` to `[]`. For `daily` / `all` only, if the main chart has no new entries, follow **Supplemental daily charts** below and use the returned repositories as the analysis candidates.
4. For each candidate, dispatch one `trend-analyze-one` sub agent in parallel. Pass `repo_full_name`, `run_dir`, and `output_language` in the prompt string. Do not bundle multiple repos into one sub agent.
5. Collect every sub agent's `RepoAnalysis` handoff. If any are missing, re-dispatch the missing ones once. After that, accept the gap and continue.
6. Render `report.md` using `assets/report-template.md`. If the main chart has no new entries, include **Changes when no repositories enter the chart**. Otherwise, leave `chart_changes_section` empty. If supplemental charts were attempted, report the candidate count and any unavailable charts in the summary, and label supplemental repositories with their language chart in the analysis sections. Fill `supplemental_statistics` with `- 补榜候选：<count>` for this branch, or leave it empty for regular runs. Before dispatching delivery, use **Writing the run result** below to write `<run_dir>/result.json` with `delivery: null`.
7. Dispatch the `trend-deliver-wecom` sub agent with one prompt string. Pass `run_dir` and `output_language`. Recommended template:

   ```
   Run trend-deliver-wecom for run_dir=<dir> with output_language=<lang>. Return one Delivery handoff.
   ```

   The sub agent owns both digest generation (writes `<run_dir>/wecom.digest.md`) and channel delivery (calls `send_wecom.py` when `WECOM_WEBHOOK_KEY` is set). It must send `<run_dir>/report.md` with attachment filename `<run_id>.md`, where `<run_id>` is the basename of `<run_dir>` and includes the date, period, and language range, for example `2026-05-03__github-trending-daily-all.md`. Capture the returned `Delivery`. Do not generate the digest yourself or call `send_wecom.py` directly.
8. Record the actual `Delivery` handoff using the delivery update command below.
9. Return a brief handoff: run_id, kept count, dropped count, report path, delivery status.

## Writing the run result

Run `python3 -m src.scripts.write_run_result --run-dir <run_dir>` with one JSON object on stdin containing `summary`, `statistics`, `analyses` (the collected `RepoAnalysis` objects), and `supplemental_candidates` (the merge output or `[]`). The script reads the snapshot and report from the run directory and writes the standard `TrendRun` object. Use this artifact writer for both updates to `result.json`.

After the delivery handoff, run `python3 -m src.scripts.write_run_result --run-dir <run_dir> --delivery` with the returned `Delivery` object on stdin. Treat a nonzero exit as an artifact-writing failure and surface its error.

## Supplemental daily charts

Fetch both Python and TypeScript, using `python` and `typescript` respectively for `<lang>`. Use the date from the main `snapshot.json` and the same run directory:

```bash
python3 src/scripts/fetch_snapshot.py --run-dir <run_dir> --snapshot-date <snapshot_date> --since daily --language <lang> --supplemental --no-bootstrap-history --allow-empty-history
```

Each successful fetch writes `snapshot.<lang>.json` under the current run. It compares with the last successful snapshot of the same supplemental chart. On its first fetch, every entry is eligible for merging. If either fetch fails, record the unavailable chart in the summary and proceed with the other chart or the main chart changes. Use only files from successful fetches in this invocation, including on a same-day retry.

Merge successful snapshots in the order `python`, `typescript` using the command below. Supply only successful file paths. If neither succeeds, keep `supplemental_candidates` empty.

```bash
python3 -m src.scripts.merge_snapshot_candidates --primary <run_dir>/snapshot.json <successful_snapshot_paths>
```

Save the returned array in `TrendRun.supplemental_candidates` unchanged. Its entries contain `repo_full_name`, `language`, `rank`, and `stars_period`. The merge keeps new entries from each supplemental chart, excludes current main-chart entries, and deduplicates repository names case-insensitively. Dispatch the same analysis and relevance screening for these repositories.

## Changes when no repositories enter the chart

When `new_in_diff == 0`, state that there were no new chart entries and include the most important observed change in the execution summary if one exists. Fill the `chart_changes_section` with a `## 在榜仓库变化` heading, the `previous_snapshot_date` if known, and up to three bullets. Translate the heading only when a different output language was explicitly requested.

- Use only current entries with a `previous_rank`. Report changes in rank and in the number of stars gained during the selected Trending period. Compare period stars only when both values are positive. Older snapshots use zero for unavailable values.
- Prioritize larger absolute rank moves, then larger absolute changes in period stars, then use the current chart order. Omit unchanged values from each bullet. Include the repo name and before/after values. For example, `- owner/repo · 周期新增 Star 326 → 494（+168）`. These are counts from the two snapshots and cannot establish a change in lifetime stars or the cause of a move.
- If there are no observed changes, explain whether the compared values were unchanged or comparable data was unavailable. The chart-change bullets do not create analysis candidates.

## Run Directory

Flat layout under `<run_dir>/`:

- `snapshot.json` — `TrendingSnapshot` with diff annotations
- `snapshot.python.json`, `snapshot.typescript.json` — supplemental snapshots when fetched
- `repo/<slug>.context.json` — per-repo `RepoContext`
- `repo/<slug>.analysis.md` — per-repo analysis Markdown
- `report.md` — rendered report; WeCom sends this content with display filename `<run_id>.md`
- `wecom.digest.md` — channel digest (only when delivery runs)
- `result.json` — final `TrendRun`

`<slug>` is `repo_full_name` with `/` replaced by `__`.

Keep all reads and writes inside the working repository directory. If gather work needs scratch space (clones, downloads), put them under `./tmp/`.

## Sub Agent Contract

Dispatch with one prompt string only. The recommended template:

```
Run trend-analyze-one for repo_full_name=<name> in run_dir=<dir> with output_language=<lang>. Return one RepoAnalysis handoff.
```

Each sub agent returns `RepoAnalysis` fields: `repo_full_name`, `disposition` (`tracked` | `adopt` | `skip`), `relevance` (`relevant` | `adjacent` | `irrelevant`), `summary`, `why`, `analysis_md` (path to its written Markdown, or null when `disposition=skip`), and optional `error`.

## Disposition Rules

- `adopt`: the repo is `relevant` or `adjacent` and worth tracking from this run forward
- `tracked`: the repo is already on a tracked list (rare — only when an external tracking state file is provided as input)
- `skip`: the repo is `irrelevant`, or evidence is too thin to justify tracking

`adopt` and `tracked` items contribute to the "新纳入跟踪" / "持续跟踪" sections. `skip` items go to "不相关或暂缓".

## Report Statistics

Compute from `analyses`:

- `screened`: `len(analyses)`
- `adopted`: count of `disposition == "adopt"`
- `tracked`: count of `disposition == "tracked"`
- `skipped`: count of `disposition == "skip"`
- `new_in_diff`: count of `entries` with `is_new == true`
- `supplemental_new`: `len(supplemental_candidates)` when supplemental charts were attempted

## Output Language

Default to concise Simplified Chinese for both `report.md` and the WeCom digest. Switch only when the user explicitly asked for another language; pass that same `output_language` into both the report rendering and the sub agent prompts so the analysis Markdowns match.
