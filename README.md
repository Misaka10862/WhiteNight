# WhiteNight · 小白

本地优先的个人 AI 智能体。她既是主人的猫娘、恋人型陪伴者和亲密朋友，也是可以完成实际工作的桌面 Agent。

- 中文名：**白夜**；昵称：**小白**；默认称呼用户：**主人**
- 首版入口：本地 WebUI（优先）→ QQ 私聊（后续阶段）
- 主脑：Ollama `qwen3-vl:8b`；复杂 GUI 任务委派 Hermes；编码任务委派 Codex
- 当前阶段：**临时最小验证方案运行中**（qwen3:8b 文本模型 + SOUL.md 人格；LoRA 暂缓；NapCat 待扫码）
- 过程性文档：[docs/PROGRESS.md](docs/PROGRESS.md) · 总览：[docs/FINAL_STATUS.md](docs/FINAL_STATUS.md)

## 仓库结构

```text
apps/web/        React + TypeScript + Vite WebUI
src/whitenight/  Python 后端（api/agent/routing/models/tools/...）
tests/           pytest 单元与集成测试
evals/           黄金评估集（人格/路由/记忆/文档/安全）
model/           训练配置与数据规范（不存权重）
docs/            ADR、协议契约与开发文档
scripts/         非破坏性开发与诊断脚本
构建计划.md      已确认的首版实施基线
```

## 快速开始

```bash
# 后端（macOS，需要 Homebrew）
brew install uv
uv python install 3.12
uv sync --dev
uv run whitenight            # 自动执行数据库迁移，http://127.0.0.1:8765

# WebUI（另开终端）
cd apps/web
npm install
npm run dev                  # http://127.0.0.1:5173，/api 与 WebSocket 已代理
```

现在可以：连续文字聊天（流式）、发送图片让小白看图、关闭并重启后继续会话。
聊天协议见 [docs/contracts/chat-ws.md](docs/contracts/chat-ws.md)。

完整环境说明见 [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)。

## 安全边界（阶段 0 已固化为代码与 ADR）

- API 只监听 `127.0.0.1`；WebUI 只允许本机回环来源。
- 数据库主密钥与服务凭据只进入 macOS Keychain；`sqlcipher://` 生产库需安装 `uv sync --extra sqlcipher`。
- 日志默认脱敏；现实动作的权限/审批引擎独立于模型输出。
- 模型权重、训练语料、密钥与数据库一律不进入 Git。

## 许可证

本项目以 MIT 许可证开源。依赖各自的许可证以 `uv.lock` / `package-lock.json` 为准；不要提交本地配置、数据库、日志、备份、密钥或模型权重。
