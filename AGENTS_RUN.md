# Running DeepTrend

From the project root, run `python3 -m src.scripts.run_pipeline`. Defaults are daily, all languages and Simplified Chinese. Pass `--dry-run` for a preview and `--artifact-root` for a separate history. On the server use `bin/run-deeptrend` for cron credentials and locking.

The script fetches the charts, compares earlier snapshots, selects today's repositories, and dispatches bounded parallel single-repository tasks. New entries and evidenced updates have distinct prompts and report sections. After analysis, the editor writes the executive summary and separate report and digest descriptions for each retained repository. The pipeline fills the existing Markdown templates with validated prose and deterministic metrics. If two attempts fail it fills the same templates from the completed analyses. The report generation mode is recorded in `result.json`. Failed checks appear in the report and cause a nonzero exit. Consult `result.json` for individual outcomes and delivery status.

Inspect the generated artifacts under the run directory when diagnosing a run. If delivery failed or the process stopped during sending, check WeCom before using `--retry-delivery` to resend the stored report. A completed delivery is reused on a same-day invocation.
