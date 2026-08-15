# 阶段 10 发布加固 实测报告（2026-08-15）

> 复跑：`uv run pytest`（125 passed, 4 skipped）；`./scripts/check.sh` 通过。

## 1. 加密备份与恢复

- 格式：`WNBK1 | salt(16B) | Fernet(token(tar.gz))`；PBKDF2-SHA256 600k 派生密钥。
- 内容：SQLite online backup（服务运行中也可备份）+ `data/attachments`。
- CLI：`generate-key / backup / verify / preview / restore`；
  恢复密钥走 `WHITENIGHT_BACKUP_KEY` 或 `--passphrase`。
- 恢复保护：`/healthz` 存活时拒绝；当前库先改名安全备份；失败自动回滚。
- **实测**：
  - 临时库：备份 → verify/preview（sessions=1, messages=1）→ 恢复替换，
    恢复前新增数据被丢弃且旧数据完整回来。
  - 错误密钥被拒（解密失败）。
  - dev 数据库真实加密备份 9869 字节，verify/preview 通过。

## 2. 诊断与日志

- `scripts/diagnostics.py --json`：DB 完整性/迁移版本/磁盘/附件/
  待审批数/Ollama/Codex/Hermes/日志尾部，实测全绿。
- 日志落盘 `data/logs/whitenight.log`（写入脱敏过滤器）。
- `/api/v1/logs?lines=N` + WebUI 日志页（5s 刷新）。

## 3. 稳定性工具

- `scripts/load_smoke.sh`：30 轮会话创建/列表/状态/删除冒烟。
- `scripts/run_72h.py --hours 72`：每分钟健康检查，异常计数与 JSONL 记录。

## 4. 文档

- `docs/INSTALL.md`：安装、首次启动、系统权限、QQ 配置、备份密钥。
- `docs/OPERATIONS.md`：健康检查、迁移回滚、备份恢复、常见故障。
- `docs/RELEASE_CHECKLIST.md`：构建计划第 18 节逐项勾稽。

## 5. 待用户执行（不能自动化）

- 72 小时持续运行 + 睡眠唤醒/网络中断实测。
- 真实浏览器视觉回归；NapCat QQ 登录与真实链路；Hermes Provider 登录。
- LoRA 训练/盲测选择默认模型；GitHub push（workflow scope）。
