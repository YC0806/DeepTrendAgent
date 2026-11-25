# DeepTrendAgent

DeepTrend 抓取 GitHub Trending，用脚本调度单仓 Agent，生成趋势报告并按配置推送企业微信。

## 跑一次

```bash
python3 -m src.scripts.run_pipeline --dry-run
```

默认抓全语言日榜，生成简体中文日报。去掉 `--dry-run` 后按 webhook 配置投递。可通过 `--since`、`--language`、`--output-language` 指定周期、榜单和输出语言。可用 `--artifact-root` 指定独立的预览目录。自然语言入口 `trend-run` 调用同一脚本。

## 执行流程

1. 抓主榜并与上一份同范围快照比较。全语言日榜没有新上榜时补查 Python 和 TypeScript 日榜，按仓库名去重。
2. **新仓库上榜**按榜单差异识别，包含重新上榜的项目。Agent 根据仓库证据判断是否值得收录。
3. **旧仓库更新**只检查当天实际抓取的榜单。用同范围历史运行中最近一次有效仓库上下文比较 release 和默认分支最新提交。有变更才派给 Agent 判断是否值得报道。老仓缺少基线时记录上下文。排名和周期 Star 的变化另列在榜变化。
4. 默认最多同时处理 4 个仓库，可用 `--workers` 或环境变量 `DEEPTREND_WORKERS` 调整。Agent 输出格式错误会重试一次。单仓失败会出现在日报并使进程返回非零。
5. 编辑 Agent 根据单仓分析撰写执行摘要、各仓库解读和企微短评。脚本按照 [日报模板](.opencode/skills/trend-run/assets/report-template.md) 和 [企微摘要模板](.opencode/skills/trend-deliver-wecom/assets/digest-template.md) 填入文案、栏目、榜单来源和统计，超长的企微摘要按整条仓库短评裁剪。编辑失败时重试一次，仍失败则将单仓分析填入相同模板。可在 `result.json` 的 `report.generation` 查看本次使用了 `agent` 还是 `template`。脚本写结果并投递。附件显示名为 `<run_id>.md`。同一日期和榜单已有成功投递时复用结果，预览后的正式运行可直接投递已生成的报告。

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

`DEEPTREND_RUN_DIR` / `DEEPTREND_RUN_ID` / `DEEPTREND_RUN_SLUG` 由 `init_run.py` 每次运行时输出，流水线通过参数传递运行目录，**不要写进 `.env`**。

## 测试

```bash
python3 -m pytest tests/
```

## 云服务器 Cron

定时入口负责加锁、获取 GitHub 凭据并启动 Python 流水线。[`bin/run-deeptrend`](bin/run-deeptrend)。

部署步骤、环境文件模板与 cron 示例见 [`deploy/README.md`](deploy/README.md)。

在项目根目录运行以下命令即可打包并部署到服务器。`deeptrend-server` 可替换为 SSH 别名或 `user@host`。

```bash
./deploy/deploy.sh deeptrend-server
```

只需要部署包时运行 `./make_package.sh`。
