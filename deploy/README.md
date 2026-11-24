# 云服务器 Cron 部署

本项目的定时入口是 `bin/run-deeptrend`。它通过 OpenCode 调用 `trend-run` skill，因此保留每个仓库的 LLM 判断、子 agent 分析、报告生成和企业微信投递。

## 打包并部署

在本地项目根目录执行：

```bash
./deploy/deploy.sh deeptrend-server
```

`deeptrend-server` 可以是 SSH 别名或 `user@host`。安装路径默认是 `/opt/deeptrend/app`，可用第二个参数指定其他绝对路径。SSH 登录用户需要能写入该路径的上级目录。服务器需要 Bash、Python 3、`tar`、`sha256sum` 和 `flock`。

脚本使用 `make_package.sh` 打包代码、技能和部署文件，通过 SSH 上传。服务器先校验 SHA-256，再解包并检查入口，最后切换 cron 使用的程序路径。版本保留在同级 `.app-releases/` 目录中。按本文部署时，环境文件、运行历史、日志和登录凭据均在程序目录之外，部署时会继续使用原有数据。

从旧版实体 `app` 目录首次升级时，请在没有任务运行的时段执行。脚本会保留原目录并将 `app` 切换为符号链接。之后的发布会原子替换这个链接，正在运行的任务继续使用它启动时的版本。部署本身不会触发日报或企业微信投递。

## 一次性准备

首次安装时，可以用同一个专用 Linux 用户（例如 `deeptrend`）来发布和执行 cron。在服务器上创建该用户后，运行 `sudo install -d -o deeptrend -g deeptrend /opt/deeptrend`，然后从本地发布代码。确保 cron 的 `PATH` 能找到已配置模型提供商的 `opencode` 和 GitHub CLI `gh`（`2.103.0` 或更高版本）。不要使用 root 运行 cron。

```bash
sudo install -d -o deeptrend -g deeptrend /var/lib/deeptrend /var/log/deeptrend /etc/deeptrend
sudo cp /opt/deeptrend/app/deploy/deeptrend.env.example /etc/deeptrend/deeptrend.env
sudo chown deeptrend:deeptrend /etc/deeptrend/deeptrend.env
sudo chmod 600 /etc/deeptrend/deeptrend.env
sudo chmod 755 /opt/deeptrend/app/bin/run-deeptrend
```

在 `/etc/deeptrend/deeptrend.env` 中填写 `WECOM_WEBHOOK_KEY` 和持久化目录。已有部署可以删除原来的 `GITHUB_TOKEN` 和 `GH_TOKEN` 配置项。OpenCode 的模型认证也必须在该用户的非交互环境可用，例如通过该用户的 OpenCode 配置或其环境变量。可选的 `OPENCODE_MODEL` 用于固定每日使用的模型。

以运行 cron 的用户登录 GitHub 一次，并在 `gh auth status` 中确认凭据可刷新。

```bash
sudo -H -u deeptrend env -u GH_TOKEN -u GITHUB_TOKEN gh auth login --hostname github.com --expiring
sudo -H -u deeptrend env -u GH_TOKEN -u GITHUB_TOKEN gh auth status --hostname github.com --active
```

每次任务启动时，入口都从该用户的 `gh` 登录获取访问令牌。`gh` 在需要时自动续签，入口只把令牌传给本次 OpenCode 进程及其子进程。若取不到令牌，任务会在启动 OpenCode 前退出，并把错误写入 cron 日志。

先以该用户手动运行一次：

```bash
sudo -H -u deeptrend /opt/deeptrend/app/bin/run-deeptrend
```

成功后检查 `/var/lib/deeptrend/trend/runs/<run_id>/result.json` 和企业微信消息。

## 安装 cron

将 `deploy/deeptrend.cron` 中的路径按实际安装位置调整，然后以 `deeptrend` 用户执行 `crontab -e` 并粘贴其内容。示例默认每天北京时间 09:10 执行。

包装脚本使用 `flock`：上次运行尚未结束时，新的触发会安全跳过，避免同一日期复用 run 目录并重复投递。

## 安全与运维

- `--auto` 是无人值守所必需的；请仅让专用用户拥有 app、数据目录与密钥文件的访问权。
- `DEEPTREND_ARTIFACT_ROOT` 必须是持久化磁盘，历史快照依赖它进行 daily diff。
- 轮换所有曾出现在历史日志或 Git 历史中的 GitHub token 与 WeCom webhook key；不要提交 `/etc/deeptrend/deeptrend.env`、`logs/` 或运行产物。
- 通过 `/var/log/deeptrend/cron.log` 查看 OpenCode 的 JSON 事件和失败原因。

## 后续 TODO

- [ ] 支持 GitHub Actions 托管日报。在 GitHub 托管 runner 上定时或手动运行 `trend-run`，恢复上一轮快照并上传本轮产物，通过 Actions Secrets 注入模型和企业微信凭据，验证内置 `GITHUB_TOKEN` 能读取所需的公开仓库数据。
