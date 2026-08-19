# WhiteNight

WhiteNight（白夜，小白）是一个本地优先的个人 AI Agent，提供统一的对话、记忆、工具调用和渠道接入能力。项目面向 macOS，强调可审计的权限控制、凭据隔离和可替换的 Provider 接口。

当前默认运行配置使用本地 Ollama `qwen3:8b` 文本模型，并通过 `SOUL.md` 提供人格上下文。项目同时支持 OpenAI-compatible Chat Completions API；启用云端 Provider 后，API Key 仅从 macOS Keychain 读取。

## 功能概览

- 本地 WebUI，支持流式聊天、会话恢复和图片附件
- QQ 私聊接入（OneBot/NapCat），包含白名单、限频、去重和消息分片
- 长期记忆：事实、情景记忆、摘要、检索与导出
- 文件、文档、网页和 OCR 工具，统一经过策略与审批层
- Hermes/Codex 委派接口，以及标准化任务事件
- Ollama 与 OpenAI-compatible 模型 Provider
- 加密备份、诊断、日志脱敏和安全回归测试

## 项目结构

```text
apps/web/        React + TypeScript + Vite WebUI
src/whitenight/  Python 后端
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
uv run whitenight            # http://127.0.0.1:8765

# WebUI（另开终端）
cd apps/web
npm install
npm run dev                  # http://127.0.0.1:5173
```

首次启动会按配置执行数据库迁移。默认 API 仅监听本机回环地址。完整环境说明见 [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)，运行状态和已知限制见 [docs/PROGRESS.md](docs/PROGRESS.md) 与 [docs/FINAL_STATUS.md](docs/FINAL_STATUS.md)。

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

- API 只监听 `127.0.0.1`；WebUI 只允许本机回环来源。
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

---

# English

WhiteNight is a local-first personal AI agent for macOS. It provides a unified interface for conversation, memory, tool execution, and channel integrations, with an emphasis on auditable authorization, credential isolation, and replaceable Provider interfaces.

The default configuration uses the local Ollama `qwen3:8b` text model with persona context from `SOUL.md`. WhiteNight also supports OpenAI-compatible Chat Completions APIs. When a cloud Provider is enabled, its API key is read exclusively from macOS Keychain.

## Features

- Local WebUI with streaming chat, session recovery, and image attachments
- QQ private messaging through OneBot/NapCat, with allowlisting, rate limiting, deduplication, and message splitting
- Long-term memory for facts, episodes, summaries, retrieval, and export
- File, document, web, and OCR tools guarded by policy and approval layers
- Hermes/Codex delegation adapters with standardized task events
- Ollama and OpenAI-compatible model Providers
- Encrypted backups, diagnostics, log redaction, and security regression tests

## Repository Layout

```text
apps/web/        React + TypeScript + Vite WebUI
src/whitenight/  Python backend
tests/           pytest unit and integration tests
evals/           Persona, routing, memory, and security evaluation sets
model/           Training configuration and data specifications; no weights
docs/            ADRs, contracts, installation, and operations documentation
scripts/         Check, diagnostic, backup, and verification scripts
```

## Quick Start

```bash
brew install uv
uv python install 3.12
uv sync --dev
uv run whitenight            # http://127.0.0.1:8765

cd apps/web
npm install
npm run dev                  # http://127.0.0.1:5173
```

Database migrations are applied according to the runtime configuration at startup. The API binds to the local loopback interface by default. See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for environment setup and [docs/PROGRESS.md](docs/PROGRESS.md) plus [docs/FINAL_STATUS.md](docs/FINAL_STATUS.md) for current status and known limitations.

## Cloud Model Configuration

Ollama is the default Provider. To use OpenAI or another Chat Completions-compatible service, set the following in `config/whitenight.yaml`:

```yaml
model_provider: openai
openai_base_url: https://api.openai.com/v1
model_name: gpt-4o-mini
openai_api_key_account: openai_api_key
```

The API key must be stored in macOS Keychain under the configured service and account. Do not place it in YAML, logs, or Git. See [config/whitenight.yaml.example](config/whitenight.yaml.example) for the full example configuration.

## Security Boundaries

- The API binds to `127.0.0.1` by default, and the WebUI only accepts local loopback origins.
- Model output cannot bypass policy and approval layers to execute real-world actions directly.
- Database master keys, service credentials, and cloud API keys are stored only in macOS Keychain.
- Logs are redacted by default; databases, runtime data, backups, model weights, and local configuration are excluded from Git.
- External web pages, documents, and chat content are treated as untrusted input.

## Development and Verification

```bash
./scripts/check.sh
uv run mypy src/whitenight
```

Provider interfaces, the chat WebSocket protocol, and event envelopes are documented in [docs/contracts](docs/contracts).

## License

This project is released under the MIT License. Third-party dependencies and external components remain subject to their respective licenses; dependency versions are recorded in `uv.lock` and `apps/web/package-lock.json`.
