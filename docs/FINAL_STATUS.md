# WhiteNight 当前状态总览（截至 2026-08-15）

> 详细过程见 [PROGRESS.md](PROGRESS.md)；各阶段实测见 `docs/reports/`。

## 结论

- 可自动化的构建工作已完成：**阶段 0–8 全部落地，阶段 9 离线工具链就绪（按用户决定暂缓训练），
  阶段 10 核心完成**。
- 当前运行方案：**临时最小验证**——本机 `qwen3:8b` 文本模型 + `SOUL.md` 预设人格；
  图片消息给出明确“暂不能看图”提示。LoRA 视觉模型为后续正式方案。
- 测试基线：**135 passed / 4 skipped**；ruff + mypy strict + 前端 eslint/tsc/vite 全绿。

## 关键能力与证据

| 能力 | 证据 |
|---|---|
| 流式聊天 + 会话恢复 | WebSocket E2E、重启恢复实测（qwen3:8b 与 qwen3-vl:8b 均验证过） |
| 长期记忆 | FTS5 + 语义混合召回、冲突/编辑/删除、真实 Ollama 提取实测 |
| 文档/OCR | PDF/DOCX/XLSX/PPTX/文本/代码/zip 语料解析；Apple Vision OCR 实测 |
| 工具与审批 | 只读自动、低风险会话授权、中高风险逐次审批、删除进废纸篓、批量删除拒绝 |
| 路由与委派 | 黄金路由集达标；Codex MCP 真实握手；Hermes 未登录安全失败 |
| WebUI | 11 个页面，会话/记忆/任务/审批/权限/模型/约束/日志/主动消息可用 |
| 后台服务 | launchd 模板、菜单栏入口、泊松主动消息、过期不补发 |
| QQ | OneBot Adapter + mock/真实模型 E2E 通过；NapCat 扫码待用户 |
| 备份恢复 | 加密备份 verify/preview/restore 实测；恢复前自动安全备份 |
| 安全 | 提示注入/SSRF/审批重放/非 owner/附件 MIME/日志脱敏红队覆盖 |

## 尚需用户完成（阻塞点）

1. **NapCat**：`/Applications/NapCatInstaller.app` 已安装并启动，需在 GUI 完成
   安装→修改 QQ→启动 NapCat→QQ 小号扫码。
2. **QQ 配置**：扫码后执行 `uv run scripts/configure_qq.py --owner <QQ号>`，
   并配置 OneBot 上报 `http://127.0.0.1:8765/api/v1/onebot/events`。
3. **72 小时运行**：`uv run scripts/run_72h.py --hours 72`。
4. **视觉回归**：本机打开 WebUI 人工确认。
5. **Hermes 真实任务**：`hermes model`/`hermes auth` 登录 Provider。
6. **LoRA**：暂缓中；GPU 与盲测流程工具已就绪。

## 恢复运行的关键命令

```bash
uv run whitenight                         # 启动服务（自动迁移）
cd apps/web && npm run dev                # WebUI
./scripts/check.sh                        # 全量检查
uv run scripts/diagnostics.py --json      # 诊断
uv run scripts/backup.py backup --output data/backups/whitenight.bak
uv run scripts/qq_link_check.py           # QQ 链路就绪检查
```

## Git

- 本地 main 与 `origin/main` 已同步（最后一次推送成功）。
- 每轮工作均有提交，tag `phase-0` 已打；发布时可按阶段补 tag。
