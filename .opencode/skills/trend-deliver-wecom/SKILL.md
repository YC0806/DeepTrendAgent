---
name: trend-deliver-wecom
description: Inspect delivery status or deliver an existing DeepTrend report when explicitly requested.
---

# DeepTrend delivery

The pipeline saves the editor’s digest to `wecom.digest.md` and records the actual delivery in `result.json`. Inspect these artifacts for delivery questions. For an explicit request to send today's saved preview, run the same `python3 -m src.scripts.run_pipeline` command with the same artifact root, period and language, without `--dry-run`. It reuses the report and records the outcome. For an interrupted or failed delivery, `--retry-delivery` resends the saved digest and attachment. Check for partial delivery first.
