# NapCat + QQ 配置步骤

> 状态：✅ 已完成（2026-08-15）。QQ 小号已扫码登录，OneBot 上报与发送均配置并实测通过。
> WebUI 登录令牌只在 NapCat 本地配置文件中，勿写入仓库/日志。

## 安装（已完成）

1. 打开 `/Applications/NapCatInstaller.app`（本会话已启动）。
2. 代理选「自动检测」，点击「安装」；如系统提示 App 管理，授予权限。
3. 安装完成后按提示「修改 QQ」→「启动 NapCat」。
4. 用 QQ 小号扫码登录；不要使用主号（降低风控影响）。

注意：安装器显示成功但刷新显示「未安装」，根因是 App Management TCC 未授权导致
root `cp` 被拒；在「系统设置 → 隐私与安全性 → App 管理」授权后重试即可。

## NapCat 网络配置（已完成）

HTTP 客户端（QQ 事件 → WhiteNight）：

- 地址：`http://127.0.0.1:8765/api/v1/onebot/events`
- 消息格式：CQ 码 / array；上报 `message.private`（群聊由 WhiteNight 忽略）。

HTTP 服务端（WhiteNight → QQ 发送）：

- 监听：`127.0.0.1:3000`（与 `qq_onebot_api_url` 一致）
- 消息格式：array；仅本机访问，token 留空。

WebUI：`http://127.0.0.1:6099/webui`（登录令牌见 NapCat 本地配置文件）。

## WhiteNight 侧配置

```bash
uv run scripts/configure_qq.py --owner <QQ小号>
# 或手动编辑 config/whitenight.yaml：
#   qq_enabled: true
#   qq_owner_ids: [<QQ小号>]
#   qq_onebot_api_url: http://127.0.0.1:3000
```

重启：`uv run whitenight`。验证：

```bash
uv run scripts/qq_link_check.py
curl http://127.0.0.1:8765/api/v1/onebot/status
# 期望：enabled=true, owner_ids=[<QQ小号>]，QQ LINK READY
```

主动消息发 QQ：把 `proactive_sender` 改为 `qq`（发送目标为 owner_ids 第一个）。

## 实测记录（2026-08-15）

- `scripts/qq_link_check.py` → `QQ LINK READY`（OneBot 3000 可达 + WhiteNight 健康 + owner 匹配）。
- 直发测试：OneBotSender → `send_private_msg`，真实 QQ 收到。
- 闭环测试：模拟 owner 私聊事件 POST 到 `/api/v1/onebot/events`，
  经 Adapter → 会话 → qwen3:8b → 回复回传，真实 QQ 收到，`get_friend_msg_history` 复核送达。

## 风险与约束

- 只有 owner_ids 中的 QQ 号能触发工具与审批；群聊忽略。
- 审批命令：`同意 <编号>` / `拒绝 <编号>`。
- NapCat 版本升级需重跑契约测试（`tests/test_onebot.py`）。
