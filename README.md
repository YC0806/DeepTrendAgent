# DeepTrendAgent

抓 GitHub trending → 对每个新仓库判断+分析 → 生成报告 → 推送到 WeCom。

整个流程由两个 skill 完成：

- `trend-run`：端到端编排。
- `trend-analyze-one`：单仓库 sub agent，并行调度。

## 跑一次

```text
请使用 trend-run skill 跑一次完整的 DeepTrend workflow。
since=daily
language=all
output_language=简体中文
跑完后返回 run_dir、report.md 路径、投递状态。
```

`trend-run` 会自动：

1. `python3 src/scripts/init_run.py` 初始化 run_dir
2. `python3 src/scripts/fetch_snapshot.py` 抓快照并对比上一轮，写 `<run_dir>/snapshot.json`
3. 并行分析新上榜仓库。全语言日榜无新上榜时，补查 Python 和 TypeScript 日榜，按仓库名去重后使用同一套筛选规则
4. 渲染 `<run_dir>/report.md`。补榜仓库会标明来源，主榜无新上榜时还会展示在榜变化
5. 如果 `WECOM_WEBHOOK_KEY` 已配置，调 `python3 src/scripts/send_wecom.py` 投递；附件显示名使用 `<run_id>.md`，例如 `2026-05-03__github-trending-daily-all.md`
6. 写 `<run_dir>/result.json`

## Run Directory 布局

```
<run_dir>/
  snapshot.json                  # TrendingSnapshot（含 is_new / previous_rank / previous_stars_period）
  snapshot.python.json          # Python 补榜快照（按需）
  snapshot.typescript.json      # TypeScript 补榜快照（按需）
  repo/
    <slug>.context.json          # 单 repo RepoContext
    <slug>.analysis.md           # 分析 Markdown
  report.md                      # canonical 报告；发送到 WeCom 时显示为 <run_id>.md
  wecom.digest.md                # WeCom digest（投递时）
  result.json                    # TrendRun
```

`<slug>` = `repo_full_name` 把 `/` 换成 `__`。

## 参数

| 参数 | 默认 | 说明 |
|------|------|------|
| `since` | `daily` | `daily` / `weekly` / `monthly` |
| `language` | `all` | GitHub trending 语言过滤 |
| `output_language` | 简体中文 | 报告和 digest 的输出语言 |

环境变量（完整列表见 `.env.example`）：

| 变量 | 说明 |
|------|------|
| `GITHUB_TOKEN` | 手动运行 Python 脚本时可选，配置后可提高 GitHub API 限额。Cron 入口会从 `gh` 登录获取 |
| `GITHUB_PROXY_URL` | 可选 HTTP(S) 代理 |
| `GITHUB_TRENDING_ARCHIVE_REPO_FULL_NAME` | archive bootstrap 来源，默认 `antonkomarev/github-trending-archive` |
| `GITHUB_TRENDING_ARCHIVE_REF` | archive 仓库 ref，默认 `main` |
| `DEEPTREND_ARTIFACT_ROOT` | run_dir 根目录。`config.py` 默认 `backend/output/trend`；`.env.example` 模板默认 `output/trend` |
| `DEEPTREND_GIT_CACHE_ROOT` | git provider 浅克隆缓存位置，默认 `<repo>/tmp/git-cache` |
| `WECOM_WEBHOOK_KEY` | 企业微信 webhook key，留空跳过投递 |

`DEEPTREND_RUN_DIR` / `DEEPTREND_RUN_ID` / `DEEPTREND_RUN_SLUG` 由 `init_run.py` 每次运行时输出，由 skill 在后续脚本调用间显式传递，**不要写进 `.env`**。

## Disposition

`trend-analyze-one` 给每个 repo 一个 disposition：

- `adopt`：相关或邻近，应纳入跟踪
- `tracked`：已经在跟踪列表（仅当外部传入 tracking state 时才用）
- `skip`：无关或证据过弱

`adopt` / `tracked` 进入"新纳入跟踪"/"持续跟踪"区段；`skip` 进入"不相关或暂缓"。

## 单独分析一个仓库

```text
请使用 trend-analyze-one skill 分析 repo_full_name=<owner/repo>，run_dir=<dir>，output_language=简体中文。返回 RepoAnalysis handoff。
```

## 测试

```bash
python3 -m pytest tests/
```

## 云服务器 Cron

完整 workflow 依赖 OpenCode 执行 `trend-run` skill，不能只把 Python 脚本按顺序串起来。仓库提供了带文件锁、持久化 artifact 根目录和非交互 OpenCode 调用的入口：[`bin/run-deeptrend`](bin/run-deeptrend)。

部署步骤、环境文件模板与 cron 示例见 [`deploy/README.md`](deploy/README.md)。

在项目根目录运行以下命令即可打包并部署到服务器。`deeptrend-server` 可替换为 SSH 别名或 `user@host`。

```bash
./deploy/deploy.sh deeptrend-server
```

只需要部署包时运行 `./make_package.sh`。
