---
name: trend-deliver-wecom
description: Generate the WeCom digest for a completed DeepTrend run by filling a fixed Simplified-Chinese template, then deliver it through the WeCom webhook channel along with the report attachment. Owns both digest authoring and channel delivery. Returns one `Delivery` handoff.
---

# Trend Deliver WeCom

One skill for the entire WeCom delivery stage of a DeepTrend run: read the run artifacts, write `wecom.digest.md` from the template, and ship to WeCom.

## Inputs

- `run_dir`: DeepTrend run directory with the report and pre-delivery artifacts. Must already contain:
  - `snapshot.json`
  - `result.json`
  - `report.md`
  - `repo/<slug>.context.json` for each repo with `disposition != "skip"`
- `output_language`: digest language (default 简体中文)

## Run Steps

1. Load run artifacts:
   - `<run_dir>/snapshot.json` → use `snapshot_date`, `since`, `language`, and the `entries` list (each entry has `rank`, `repo_full_name`, `stars_period`).
   - `<run_dir>/result.json` → use `analyses` and `supplemental_candidates` (default `[]`). Highlighted repos = those with `disposition != "skip"`. Match supplemental repositories by case-insensitive `repo_full_name`; use the saved chart language, rank, and period stars.
   - For each highlighted repo, read `<run_dir>/repo/<slug>.context.json` and pick `stars_total`. `<slug>` = `repo_full_name.replace("/", "__")`. If the context file is missing or `stars_total` is 0, omit the ⭐ segment for that line — do not fabricate a number.

2. Render the digest by filling `assets/digest-template.md`:
   - Use `重点仓库` and the main chart rank by default. If supplemental highlights exist, use `补充发现`, in `supplemental_candidates` order, and label the rank with the language chart, such as `Python 日榜 #3`.
   - If there are no highlights and the main snapshot has no new entries, use the report's `在榜仓库变化` heading and copy its bullet lines in order. Use the localized heading when applicable. If that section is unavailable, use the ordinary empty fallback below.
   - Build one bullet for each highlighted repository:
     `- {repo_full_name}（{segments}）：{description}。`
   - `segments` is a ` · ` joined list, including only segments whose values are present and non-zero, in this order:
     1. `#{rank}` or the supplemental language chart and rank
     2. `⭐{stars_total_fmt}`
     3. `+{stars_period_fmt}`
     4. `{relevance_label}`
   - `relevance_label` mapping: `relevant` → `核心`, `adjacent` → `相关`. Skip the segment for any other value.
   - Star formatting: `n >= 1_000_000` → `{n/1_000_000:.1f}M` (drop `.0` if integer-valued in M); `n >= 10_000` → `{round(n/1000)}k`; `n >= 1_000` → `{n/1000:.1f}k` (drop `.0`); else the raw integer.
   - `description`: 2–3 sentences covering use case, core technical approach, and key capabilities. Take `RepoAnalysis.summary` as the source of truth — light polishing for flow is fine, but do not introduce facts not present in summary or the analysis Markdown. Output in `output_language`. Trim trailing punctuation before joining; the template appends `。`.

3. Enforce the 2048-character total cap (Chinese characters count as 1):
   - If the assembled digest exceeds 2048 characters, drop highlighted lines from the end, append `- 其余重点仓库详见附件。` once at the end, and re-measure. Repeat until it fits.
   - Footer fallbacks if items keep getting dropped: `- 详见附件。` then `详见附件。` then no footer.
   - If there are no highlighted repos or chart-change bullets to show, the body becomes `- 本期无重点仓库，详见附件。`.

4. Write the final digest to `<run_dir>/wecom.digest.md` (UTF-8, no trailing whitespace).

5. Call `send_wecom.py`:
   ```
   python3 src/scripts/send_wecom.py --summary-path <run_dir>/wecom.digest.md --attachment-path <run_dir>/report.md --attachment-filename <run_id>.md
   ```
   `<run_id>` is the basename of `<run_dir>`, for example `2026-05-03__github-trending-daily-python`. This keeps the canonical artifact path as `<run_dir>/report.md`, while the WeCom attachment displays a date / period / language-range filename such as `2026-05-03__github-trending-daily-python.md`.

   Parse its stdout JSON as the `Delivery` to return. The script reads `.env` itself and emits `status="skipped"` when `WECOM_WEBHOOK_KEY` is absent — no pre-check needed.

6. Return the `Delivery`.

## Handoff Contract

Return one `Delivery`:

- `channel`: `"wecom"`
- `status`: `"success"` | `"skipped"` | `"failed"`
- `summary`: short human-readable reason
- `sent_at`: ISO 8601 UTC timestamp
- `error`: null when status is `success`/`skipped`; otherwise a short error string

## Notes

- This skill is the authoritative source for `wecom.digest.md`. The orchestrator (`trend-run`) should not generate the digest itself or shell out to a separate digest-building script.
- The 2048 cap is the WeCom markdown message hard limit. `send_wecom.py` re-validates it and will reject anything longer.
- `send_wecom.py` reads `.env` by itself; the orchestrator does not need to thread `WECOM_WEBHOOK_KEY` through.
