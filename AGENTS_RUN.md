# DeepTrend Run Guidelines

Run-mode handbook for executing the existing `trend-run` / `trend-analyze-one` workflow. Do not redesign the workflow or patch code during a run.

## When To Use

- When the user asks to "run DeepTrend", "generate a trend report", or "send a DeepTrend report", use the `trend-run` skill.
- `trend-run` is the only end-to-end orchestrator: initialize the run, fetch the snapshot, identify new repositories, dispatch per-repo analysis in parallel, render the report, deliver it, and write `result.json`.
- `trend-analyze-one` handles exactly one repository: build repo context, judge relevance, decide disposition, write analysis Markdown, and return one `RepoAnalysis` handoff.

## Default Inputs

- `since`: `daily`, unless the user specifies `weekly` or `monthly`.
- `language`: `all`, unless the user specifies a GitHub Trending language filter.
- `output_language`: Simplified Chinese, unless the user explicitly requests another language.

Pass the same `output_language` to report rendering and every `trend-analyze-one` prompt so the report and per-repo analyses use the same language.

## Run Flow

1. Initialize the run directory:

   ```bash
   python3 src/scripts/init_run.py --since <since> --language <language>
   ```

   Read `run_dir` from the stdout JSON. Pass `--run-dir <run_dir>` explicitly to every later script. Do not rely on `DEEPTREND_RUN_*` values printed by a previous shell command being inherited automatically.

2. Fetch and diff the snapshot:

   ```bash
   python3 src/scripts/fetch_snapshot.py --run-dir <run_dir> --since <since> --language <language>
   ```

   On success, read `<run_dir>/snapshot.json`. If stderr contains `previous snapshot is required for diff` or `no historical snapshot was found`, this is a first-run or archive-gap case; retry the same command once with `--allow-empty-history`. For any other error, stop and return stderr.

3. Select repositories where `snapshot.entries[*].is_new == true`, preserving snapshot order. When `daily` / `all` has no new entries, follow the `trend-run` **Supplemental daily charts** instructions to produce the analysis candidates.

4. Dispatch one `trend-analyze-one` sub agent per candidate in parallel. Each sub agent handles exactly one `repo_full_name`; do not bundle multiple repositories into one agent.

5. Collect all `RepoAnalysis` handoffs. Re-dispatch missing repositories at most once. If any handoffs are still missing, accept the gap and continue report generation.

6. Render `<run_dir>/report.md` using `.opencode/skills/trend-run/assets/report-template.md`, and build a `TrendReport` with:

   - `summary`
   - `markdown`
   - `statistics`: `screened`, `adopted`, `tracked`, `skipped`, `new_in_diff`

   For a main snapshot with no new entries, follow the `trend-run` chart-changes instructions to surface observed rank and period-star changes. Label supplemental analyses with their chart language. Before dispatching delivery, use the artifact writer specified by `trend-run` to write `<run_dir>/result.json` with `delivery: null`.

7. Dispatch the `trend-deliver-wecom` sub agent. It owns both digest authoring (writes `<run_dir>/wecom.digest.md` from the fixed template, ≤ 2048 chars) and channel delivery (calls `send_wecom.py` when `WECOM_WEBHOOK_KEY` is set; otherwise returns a `skipped` Delivery). It must send `<run_dir>/report.md` with WeCom attachment filename `<run_id>.md`, for example `2026-05-03__github-trending-daily-all.md`, so the displayed file name includes date, period, and language range. Capture the returned `Delivery`. Do not generate the digest yourself or invoke `send_wecom.py` directly.

8. Record the actual `Delivery` handoff with the artifact writer's `--delivery` option.

## Sub Agent Dispatch Contract

`trend-run` dispatches `trend-analyze-one` with a single prompt string. Recommended format:

```text
Run trend-analyze-one for repo_full_name=<name> in run_dir=<dir> with output_language=<lang>. Return one RepoAnalysis handoff.
```

The prompt must include:

- `repo_full_name`
- `run_dir`
- `output_language`

If the tool supports environment variables, also pass `DEEPTREND_RUN_DIR`, `DEEPTREND_RUN_ID`, and `DEEPTREND_RUN_SLUG`. Script calls should still prefer explicit `--run-dir`.

## RepoAnalysis Contract

Each sub agent returns one `RepoAnalysis`:

- `repo_full_name`: input repository name
- `disposition`: `tracked` | `adopt` | `skip`
- `relevance`: `relevant` | `adjacent` | `irrelevant`
- `summary`: short factual summary
- `why`: reason for the disposition
- `analysis_md`: `<run_dir>/repo/<slug>.analysis.md` for `adopt` / `tracked`, or null for `skip`
- `error`: null on success; short error message on failure

If `fetch_repo_context.py` fails or the context is empty, do not fabricate an analysis from the repository name. Return `skip`, `irrelevant`, and a non-null `error`.

## Disposition Rules

- `adopt`: directly relevant to agent / LLM infra / RAG / eval observability / tool ecosystem, or adjacent and worth tracking.
- `tracked`: use only when explicit external tracking state says this repository is already tracked.
- `skip`: outside the focus domain, or evidence is too thin to justify tracking.

Report sections:

- `adopt` -> "Newly Adopted Repositories"
- `tracked` -> "Continuously Tracked Repositories"
- `skip` -> "Irrelevant or Deferred Repositories"

## Statistics

Compute from `analyses` and `snapshot.entries`:

- `screened`: `len(analyses)`
- `adopted`: count where `disposition == "adopt"`
- `tracked`: count where `disposition == "tracked"`
- `skipped`: count where `disposition == "skip"`
- `new_in_diff`: count of `snapshot.entries` where `is_new == true`
- `supplemental_new`: count of `supplemental_candidates` when supplemental charts were attempted

## Run Directory

Each run creates a flat run directory via `src/scripts/init_run.py`:

```text
<run_dir>/
  snapshot.json
  snapshot.python.json / snapshot.typescript.json  # when supplemental charts are fetched
  repo/
    <slug>.context.json
    <slug>.analysis.md
  report.md          # canonical report artifact; WeCom attachment filename is <run_id>.md
  wecom.digest.md
  result.json
```

`<slug>` is `repo_full_name` with `/` replaced by `__`.

All run-local artifacts must stay inside `<run_dir>`. Put temporary clones, downloads, or scratch files under repository-local `./tmp/`.

## Execution Boundaries

Do not modify code or workflow definitions in run mode unless the user explicitly asks to debug or fix them.

Do not modify:

- `.opencode/skills/**`
- `src/scripts/**`
- `src/tools/**`
- `src/provider/**`
- `src/models.py`
- `README.md`
- `docs/**`

Allowed write targets:

- `<run_dir>/**`
- `./tmp/**` when necessary

## Failure Handling

Classify the failure before deciding whether to retry:

1. Parameter or input failure: missing CLI argument, invalid date format, missing prompt field, or missing `run_dir`. Fix and retry only if no code change is needed.
2. First-run or archive-gap failure: only when `fetch_snapshot.py` clearly reports missing previous/history data, retry once with `--allow-empty-history`.
3. Implementation or environment failure: Python exception, provider/network/auth issue, contract mismatch, missing dependency, or WeCom delivery failure. Stop and return stderr verbatim. Do not silently patch code or bypass scripts.

Do not edit code, invent business input, handwrite missing artifacts, or move judgment logic back into Python just to make a run succeed.

## Return Format

On success, return:

- `run_id`
- `run_dir`
- `<run_dir>/result.json`
- `<run_dir>/report.md` (sent to WeCom as `<run_id>.md`)
- delivery status
- brief summary: screened count and adopt/tracked/skip counts

On failure, return:

- failed stage or script
- stderr verbatim
- paths of artifacts already written
- whether the run can be retried without code changes
