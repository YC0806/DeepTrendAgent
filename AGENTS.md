# DeepTrend Agent Repository Guidelines

## 架构总览

DeepTrend 只有两个 skill：

- `trend-run`：端到端编排。初始化 run、抓快照、并行调度 per-repo 分析、渲染报告、投递。
- `trend-analyze-one`：单仓库 sub agent。建 repo context、判断相关性、决定 disposition、写 analysis Markdown。

`trend-run` 通过单条 prompt string 派发 `trend-analyze-one`，每次只针对一个 `repo_full_name`。所有 workflow 控制权都在 skill 层，不在 Python 里。

## 职责边界

- `provider` 只做：抓外部资源、读写历史 artifact、序列化原始数据。
- `tools` 只做：归一化、上下文组装、单一目的的转换、digest 拼装等纯函数辅助。
- `skill` 是唯一的 workflow owner，做所有业务判断（relevance、disposition、报告叙事）。

不要把判断逻辑搬回 `tools` 或 `provider`。不要新建 `agents/` 目录或 `orchestrator.py`。

## Run Directory

每次运行都有一个由 `src/scripts/init_run.py` 创建的扁平 run_dir：

```
<run_dir>/
  snapshot.json                # TrendingSnapshot（含 is_new / previous_rank / history_source）
  repo/
    <slug>.context.json        # RepoContext
    <slug>.analysis.md         # 分析 Markdown
  report.md                    # 渲染后的报告；发送到 WeCom 时显示为 <run_id>.md
  wecom.digest.md              # WeCom digest（投递时生成）
  result.json                  # TrendRun
```

`<slug>` = `repo_full_name` 把 `/` 换成 `__`。

环境变量：`DEEPTREND_RUN_DIR`、`DEEPTREND_RUN_ID`、`DEEPTREND_RUN_SLUG`。所有 sub agent 都应把这些值视为当前 run 的默认上下文。run-local 产物必须落在 `DEEPTREND_RUN_DIR` 内。

## 关键脚本

| 脚本 | 职责 |
|------|------|
| `src/scripts/init_run.py` | 初始化 run_dir，emit 元数据 |
| `src/scripts/fetch_snapshot.py` | 抓 GitHub trending、对比上一轮、写 `snapshot.json`（带 diff 注解） |
| `src/scripts/fetch_repo_context.py` | 为单 repo 写 `RepoContext` 到 `<run_dir>/repo/<slug>.context.json` |
| `src/scripts/send_wecom.py` | 调用 WeCom webhook，发送 digest + 附件 |

脚本是薄 CLI，不持有 workflow 状态。

## 分析深度

`trend-analyze-one` 默认只用仓库级信号（README + releases + description + topics + last commit）。只有当 analysis Markdown 中的某个具体论断需要源代码层面的证据时，才调一次 `get_git_repo_tree` 或 `get_git_repo_file_content` 做窄目标确认。不要做仓库级的源码审计或提交历史研究。

## 设计判断方法

新增逻辑前先问：

1. 它在回答"有什么事实可用 / 怎么归一化"——放 `provider` 或 `tools`。
2. 它在回答"这个 repo 怎么定性 / 是否相关 / 怎么写分析"——放 `trend-analyze-one`。
3. 它在回答"接下来跑什么 / 是否要继续"——放 `trend-run`。
