# WhiteNight

[Chinese description](README-zh.md)

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
