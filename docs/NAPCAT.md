# NapCat + QQ 配置步骤

## 安装（已完成到启动安装器）

1. 打开 `/Applications/NapCatInstaller.app`（本会话已启动）。
2. 代理选「自动检测」，点击「安装」；如系统提示 App 管理，授予权限。
3. 安装完成后按提示「修改 QQ」→「启动 NapCat」。
4. 用 QQ 小号扫码登录；不要使用主号（降低风控影响）。

## NapCat WebUI 配置 OneBot 上报

1. 浏览器打开 `http://127.0.0.1:6099/webui`（默认）。
2. 网络配置 → 新增 HTTP 服务器/上报：
   - 地址：`http://127.0.0.1:8765/api/v1/onebot/events`
   - 消息格式：CQ 码；上报类型至少勾选 `message.private`。
3. 保存后测试发送一条私聊消息，WhiteNight 日志应出现 QQ 处理记录。

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
curl http://127.0.0.1:8765/api/v1/onebot/status
# 期望：enabled=true, owner_ids=[<QQ小号>]
```

## 风险与约束

- 只有 owner_ids 中的 QQ 号能触发工具与审批；群聊忽略。
- 审批命令：`同意 <编号>` / `拒绝 <编号>`。
- NapCat 版本升级需重跑契约测试（`tests/test_onebot.py`）。
