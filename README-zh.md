# WhiteNight

[English README](README.md)

WhiteNight（白夜，小白）是一个面向 macOS 的本地优先个人 AI Agent，提供统一的对话、记忆、工具调用和渠道接入能力。项目强调可审计的权限控制、凭据隔离和可替换的 Provider 接口。

除实用的自动化能力外，WhiteNight 还针对细腻、连续的情感陪伴进行了专门优化：通过人格感知提示、长期记忆、跨会话连续性、基于语境的语气调整和可选的主动消息，支持更稳定、更尊重用户边界的长期关系体验，同时始终保留明确的安全与权限边界。

当前默认配置使用本地 Ollama `qwen3:8b` 文本模型，并通过 `SOUL.md` 提供人格上下文。项目同时支持 OpenAI-compatible Chat Completions API；启用云端 Provider 后，API Key 仅从 macOS Keychain 读取。

## 功能概览

- 本地 WebUI，支持流式聊天、会话恢复和图片附件
- QQ 私聊接入（OneBot/NapCat），包含白名单、限频、去重和消息分片
- 长期记忆：事实、情景记忆、摘要、检索与导出
- 面向情感陪伴的优化：人格连续性、语境化语气和关系感知记忆
- 文件、文档、网页和 OCR 工具，统一经过策略与审批层
- 可选 Hermes 与显式 `/codex` 委派接口，以及标准化任务事件
- Ollama 与 OpenAI-compatible 模型 Provider
- 加密备份、诊断、日志脱敏和安全回归测试

Hermes 委派默认暂时关闭，电脑操作请求留在小白本体的工具层。只有以 `/codex` 开头的消息
才会调用 Codex；普通编码请求继续由小白处理。

当前版本面向 macOS，并通过 OneBot/NapCat 接入 QQ。渠道与 Provider 均保持可替换，后续可在不改变核心对话、记忆、权限和人格模型的前提下，逐步扩展到更多操作系统与更广泛的聊天软件。

## 项目结构

```text
apps/web/        React + TypeScript + Vite WebUI
src/whitenight/  Python 后端
tests/           pytest 单元与集成测试
evals/           人格、路由、记忆和安全评估集
model/           训练配置与数据规范，不包含模型权重
docs/            ADR、协议契约与安装运维文档
scripts/         检查、诊断、备份和验证脚本
```

## 快速开始

```bash
# 后端（macOS，需要 Homebrew）
brew install uv
uv python install 3.12
uv sync --dev
uv run whitenight            # http://127.0.0.1:8765

# WebUI（另开终端）
cd apps/web
npm install
npm run dev                  # http://127.0.0.1:5173
```

首次启动会按运行配置执行数据库迁移。默认 API 仅监听本机回环地址。完整环境说明见 [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)，运行状态和已知限制见 [docs/PROGRESS.md](docs/PROGRESS.md) 与 [docs/FINAL_STATUS.md](docs/FINAL_STATUS.md)。

## 云端模型配置

默认 Provider 为 Ollama。如需使用 OpenAI 或其他兼容 Chat Completions 的服务，在 `config/whitenight.yaml` 中设置：

```yaml
model_provider: openai
openai_base_url: https://api.openai.com/v1
model_name: gpt-4o-mini
openai_api_key_account: openai_api_key
```

API Key 必须写入 macOS Keychain 对应服务和账户；不得写入 YAML、日志或 Git。详细配置示例见 [config/whitenight.yaml.example](config/whitenight.yaml.example)。

## 安全边界

- API 默认只监听 `127.0.0.1`，WebUI 仅允许本机回环来源。
- 模型输出不能绕过权限和审批层直接执行现实操作。
- 数据库主密钥、服务凭据和云端 API Key 只进入 macOS Keychain。
- 日志默认脱敏；数据库、运行数据、备份、模型权重和本地配置不纳入 Git。
- 外部网页、文档和聊天内容均视为不可信输入。

## 开发与验证

```bash
./scripts/check.sh
uv run mypy src/whitenight
```

Provider 接口、聊天 WebSocket 和事件信封见 [docs/contracts](docs/contracts)。

## 许可证

本项目以 MIT License 发布。第三方依赖及外部组件按照各自许可证使用，依赖版本记录在 `uv.lock` 和 `apps/web/package-lock.json` 中。
