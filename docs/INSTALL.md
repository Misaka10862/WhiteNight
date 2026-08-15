# 安装与首次启动

## 1. 前置

- macOS（Apple Silicon 实测），Homebrew
- Node.js 20+（WebUI 开发）与 `uv`
- Ollama 已安装并拉取模型：`ollama pull qwen3-vl:8b`
- 可选：`uv sync --extra sqlcipher`（生产加密库）、`--extra ocr`（Apple Vision OCR）

## 2. 安装

```bash
git clone <私有仓库地址> WhiteNight
cd WhiteNight
brew install uv || curl -LsSf https://astral.sh/uv/install.sh | sh
uv python install 3.12
uv sync --dev
uv run alembic upgrade head
cp config/whitenight.yaml.example config/whitenight.yaml
```

## 3. 首次启动

```bash
uv run whitenight            # http://127.0.0.1:8765，自动迁移
cd apps/web && npm install && npm run dev   # http://127.0.0.1:5173
```

打开 WebUI → 模型页确认 Ollama 健康；聊天页发送“你好”验证链路。

## 4. 系统权限（按需授予）

| 能力 | 系统设置位置 | 说明 |
|---|---|---|
| 截图 | 隐私与安全性 → 屏幕录制 | 授予终端/whitenight |
| GUI 操作（Hermes） | 辅助功能 + 屏幕录制 | `hermes computer-use permissions grant` |
| 废纸篓删除 | 自动化（Finder） | 首次执行时 macOS 会提示 |
| 后台自启 | 登录项 | `./scripts/install_launchd.sh --install` |

## 5. QQ 配置

1. 从 NapCatQQ 官方渠道下载构建，扫码登录专用 QQ 小号。
2. 配置 OneBot HTTP 上报到 `http://127.0.0.1:8765/api/v1/onebot/events`。
3. 在 `config/whitenight.yaml` 设置：

```yaml
qq_enabled: true
qq_owner_ids: [你的QQ号]
qq_onebot_api_url: http://127.0.0.1:3000
```

4. 重启 WhiteNight，在模型页确认 QQ/OneBot 状态。

## 6. 备份恢复密钥

```bash
uv run scripts/backup.py generate-key   # 打印后离线保存
uv run scripts/backup.py backup --output data/backups/whitenight.bak
uv run scripts/backup.py preview --input data/backups/whitenight.bak
```

恢复前停止服务：`uv run scripts/backup.py restore --input data/backups/whitenight.bak`
