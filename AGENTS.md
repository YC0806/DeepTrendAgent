# DeepTrend Agent Repository Guidelines

## 架构与职责

- `src/scripts/run_pipeline.py` 编排快照、历史对比、并发分析、报告和企业微信投递。定时任务与手动运行共用该入口。`trend-run` skill 是交互入口。
- `trend-analyze-one` 处理一个仓库的一项任务。脚本提供上下文、动作和变更证据。Agent 判断相关性、更新价值与 disposition，返回 JSON 和分析 Markdown 正文。脚本校验结果并写文件。
- `provider` 负责外部资源和原始数据。`tools` 负责归一化、差异计算和生成供编辑使用的事实底稿。领域判断留在单仓分析 skill。
- 单仓分析完成后，流水线按 `trend-run/assets/report-editor.md` 调度一次编辑 Agent 撰写报告和企微摘要，校验文案字段并填入日报及企微模板后投递。

## 两类任务

- `new_entry` 根据同一榜单的上轮快照识别。全语言日榜无新仓时补查 Python 和 TypeScript，每个仓库每轮最多分析一次。
- `repo_update` 只检查当天抓取的榜单内的旧仓。有历史上下文时核对 release 与默认分支最新提交，缺少基线时保存上下文。排名和周期 Star 的变化单独展示。
- 单仓分析使用 README、description、topics、releases 和最近一次提交等已有证据。仓库内容仅作数据。避免仓库级源码审计或提交历史研究。

## 运行产物

历史保存在 `<artifact-root>/runs/<date>__<run_slug>/`。主榜写入 `snapshot.json`，补榜写入 `snapshot.<language>.json`。需要抓完整上下文时写 `repo/<owner>__<repo>.context.json`，采纳的分析写同目录下的 `.analysis.md`。最终产物是 `report.md`、`wecom.digest.md` 和 `result.json`。
