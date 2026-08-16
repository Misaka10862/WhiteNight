# WhiteNight 当前状态总览（截至 2026-08-15）

> 详细过程见 [PROGRESS.md](PROGRESS.md)；各阶段实测见 `docs/reports/`。

## 结论

- 可自动化的构建工作已完成：**阶段 0–8 全部落地，阶段 9 离线工具链就绪（按用户决定暂缓训练），
  阶段 10 核心完成**。
- 当前运行方案：**临时最小验证**——本机 `qwen3:8b` 文本模型 + `SOUL.md` 预设人格；
  图片消息给出明确“暂不能看图”提示。LoRA 视觉模型为后续正式方案。
- 测试基线：**142 passed / 4 skipped**；ruff + mypy strict + 前端 eslint/tsc/vite 全绿。
- 真实 QQ 链路已打通（NapCat 扫码 + OneBot 上报/发送 + owner 白名单 + 收发闭环实测）。
- 72 小时持续运行巡检进行中（由 Agent 启动，当前 0 失败）。

## 关键能力与证据

| 能力 | 证据 |
|---|---|
| 流式聊天 + 会话恢复 | WebSocket E2E、重启恢复实测；qwen3:8b 常驻（keep_alive=-1），QQ 闭环回复 4.5s |
| 长期记忆 | FTS5 + 语义混合召回、冲突/编辑/删除、真实 Ollama 提取实测；提取限长 512 token，聊天优先取消占用 |
| 文档/OCR | PDF/DOCX/XLSX/PPTX/文本/代码/zip 语料解析；Apple Vision OCR 实测 |
| 工具与审批 | 只读自动、低风险会话授权、中高风险逐次审批、删除进废纸篓、批量删除拒绝 |
| 路由与委派 | 黄金路由集达标；Codex MCP 真实握手；Hermes 未登录安全失败 |
| WebUI | 11 个页面，会话/记忆/任务/审批/权限/模型/约束/日志/主动消息可用；模型页可切换 Ollama 常驻策略（即时生效并持久化） |
| 后台服务 | launchd 模板、菜单栏入口、泊松主动消息、过期不补发 |
| QQ | NapCat 真实部署：QQ 小号登录，OneBot 上报（8765）与发送（3000）配置完成，`QQ LINK READY`，直发与事件闭环实测送达；戳一戳 poke 段可识别并生成专属反应 |
| 备份恢复 | 加密备份 verify/preview/restore 实测；恢复前自动安全备份 |
| 安全 | 提示注入/SSRF/审批重放/非 owner/附件 MIME/日志脱敏红队覆盖；生成强制 `num_predict` 上限防失控占用推理槽 |

## 尚需用户完成（阻塞点）

1. **72 小时运行**：Agent 已启动 `scripts/run_72h.py --hours 72`，进行中；
   运行期间如遇睡眠唤醒/网络中断会自动记录，用户无需额外操作。
2. **视觉回归**：本机打开 WebUI 做一次人工确认（桌面/窄窗口截图已由 headless 生成）。
3. **Hermes 真实任务**：`hermes model`/`hermes auth` 登录 Provider 后跑真实任务链路。
4. **Codex 真实任务**：MCP 握手已通过；是否消耗云端配额跑一个短任务需用户确认。
5. **LoRA**：暂缓中；GPU 租用计划与盲测流程工具已就绪。
6. **主动消息发 QQ（可选）**：把本地 `config/whitenight.yaml` 的
   `proactive_sender` 改为 `qq` 即启用（目标为 owner_ids 第一个；默认 log）。

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
