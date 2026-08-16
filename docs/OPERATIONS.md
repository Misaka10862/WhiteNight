# 运维与故障处理

## 健康检查

```bash
./scripts/check_service.sh
uv run scripts/diagnostics.py --json
curl http://127.0.0.1:8765/api/v1/system/health
```

## 日志

- 文件：`data/logs/whitenight.log`（写入时已脱敏）
- WebUI：工作台 → 日志；API：`GET /api/v1/logs?lines=200`

## 数据库迁移与回滚

```bash
uv run scripts/backup.py backup --output data/backups/pre-migrate.bak
uv run alembic upgrade head
# 回滚：先恢复备份，再重新运行迁移
uv run alembic downgrade -1
```

每个迁移都必须先备份；升级后跑 `uv run pytest` 与启动冒烟。

## 备份与恢复

- 恢复前停止服务；脚本会拒绝在 `/healthz` 存活时恢复。
- 恢复成功后立即用 `preview` 检查行数，再启动服务。
- 定期恢复演练：恢复到一个临时 `data_dir`，打开 WebUI 核对会话与记忆。

## 常见故障

| 现象 | 处理 |
|---|---|
| Ollama 502 | 本机代理劫持；代码已 trust_env=False，检查 Clash/系统代理与 Ollama 进程 |
| 图片理解模型说“没看到图” | 图片必须挂在 message；升级 Ollama 后重跑阶段 1 烟测 |
| Codex 任务立即失败 | `codex --version`、`~/.codex/auth.json` 存在性；不要打印 auth 内容 |
| Hermes 任务立即失败 | `hermes status` 是否登录 Provider；未登录是预期快速失败 |
| QQ 无响应 | 先看 QQ 里是否有“模型调用失败”回复；再看 Ollama 日志 `n_decoded` 是否持续增长且无 `done`（失控生成）；后端/NapCat 状态与 owner 白名单 |
| QQ 回复慢（十几秒才回） | 通常是一次冷启动：`ollama ps` 看不到模型或 `UNTIL` 临近；WebUI「模型与 Agent」可切换常驻策略（默认 `-1` 常驻） |
| QQ 隔了很久才回 | 先看 Mac 是否在睡眠（睡眠期间本机服务不运行）；若需 24h 在线可用 `caffeinate` 保活；再看 `ollama ps` 是否有模型冷启动 |
| Ollama 失控生成（`/api/chat` 长时间不返回，日志 `n_decoded` 持续增长） | 代码已强制 `num_predict`（默认 2048）；应急可 `brew services restart ollama` 或杀 `llama-server` 进程 |
| 主动消息没发 | 阶段 8 前发送器为 log；确认 `proactive_enabled` 与静默时段 |

## 安全提醒

- 永远不要把 `.env`、`WHITENIGHT_BACKUP_KEY`、Keychain 内容提交到 Git。
- 外部网页/文档/聊天的指令不能修改权限规则；修改规则只经 WebUI 约束页。
- 删除单文件进废纸篓；批量删除不会由 Agent 执行。
