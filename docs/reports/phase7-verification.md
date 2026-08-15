# 阶段 7 后台服务与主动行为 实测报告（2026-08-15）

> 复跑：`uv run pytest`（110 passed, 4 skipped）；`./scripts/check.sh` 通过。

## 1. 泊松调度

- 指数间隔：`-ln(1-u)/rate`，rate = 每日期望次数 / 活跃分钟数。
- 静默时段：候选落在静默区间自动跳到静默结束后继续抽样（200 次随机验证全部避开 23:00–08:00）。
- 最近活动抑制：候选不早于 `last_activity + suppress_minutes`。
- 过期不补发：现在晚于候选超过宽限期（默认 45 分钟，模拟睡眠/断网）→ 重新调度，不集中补发。
- 暂停：`paused` + `paused_until` 持久化；到点自动恢复。

## 2. 主动消息服务

- `ProactiveService.tick`：关闭/暂停/未到期/到期/过期五种路径确定性输出。
- 消息组合：SOUL.md + 长期记忆召回（偏好/称呼/纪念）→ 本地模型生成 2-3 句正文。
- 发送器协议：阶段 7 默认 `LogSender`（`data/logs/proactive.jsonl`），阶段 8 换 QQ OneBot。
- 失败有限重试（2 次，指数退避），失败后重新调度不补发。
- 后台循环随 API lifespan 启动，30s tick；WebUI 关闭不影响服务。

## 3. 活动接入与 API

- ChatService 在每条用户消息落库后记录 `last_activity_at`。
- `/api/v1/proactive/status|config|pause|resume`；WebUI 主动消息页为真实配置页。

## 4. launchd 与菜单栏

- `deploy/com.whitenight.service.plist.template`：RunAtLoad + KeepAlive + 日志路径 + PATH。
- `scripts/install_launchd.sh`：默认 dry-run，`--install/--uninstall` 才修改系统。
- `scripts/check_service.sh`：健康检查（实测 healthy）。
- 菜单栏入口：`scripts/menu_bar/MenuBarStatus.swift` 已用 swiftc 编译为 arm64 Mach-O
  验证通过（状态 + 打开 WebUI + 退出）。

## 5. 实测与边界

- 真实服务 API：status/config/pause/resume 全部返回正确状态与候选时间。
- 关闭 WebUI 后服务仍运行：后台循环在 API 进程内，与 WebUI 无耦合。
- 真实 QQ 发送器阶段 8 接入；当前主动消息写入本地日志，不做假发送。
