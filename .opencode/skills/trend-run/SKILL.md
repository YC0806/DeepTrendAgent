---
name: trend-run
description: Launch the DeepTrend script and report its result.
---

# Run DeepTrend

Invoke `python3 -m src.scripts.run_pipeline` once from the project root. Pass the requested `--since`, `--language`, and `--output-language` values. Use `--dry-run` when the user asks to preview without sending. Cron uses `bin/run-deeptrend` to acquire the run lock and refresh GitHub credentials before calling the same pipeline.

Return the run directory, report path, statistics and delivery status from the script. Surface a nonzero exit and its diagnostic. The script owns chart selection, agent dispatch, the final editorial call, output validation and delivery.
