# WhiteNight

[Chinese description](README-zh.md)

WhiteNight is a local-first personal AI agent for macOS. It provides a unified interface for conversation, memory, tool execution, and channel integrations, with an emphasis on auditable authorization, credential isolation, and replaceable Provider interfaces.

In addition to practical automation, WhiteNight includes dedicated optimizations for emotionally attentive companionship. Persona-aware prompting, long-term memory, continuity across sessions, context-sensitive tone, and optional proactive messaging are designed to support a more consistent and respectful relationship over time while preserving explicit safety and permission boundaries.

The default configuration uses the local Ollama `qwen3:8b` text model with persona context from `SOUL.md`. WhiteNight also supports OpenAI-compatible Chat Completions APIs. When a cloud Provider is enabled, its API key is read exclusively from macOS Keychain.

## Features

- Local WebUI with streaming chat, session recovery, and image attachments
- QQ private messaging through OneBot/NapCat, with allowlisting, rate limiting, deduplication, and message splitting
- Long-term memory for facts, episodes, summaries, retrieval, and export
- Emotionally attentive companionship with persona continuity, contextual tone, and relationship-aware memory
- File, document, web, and OCR tools guarded by policy and approval layers
- Optional Hermes and explicit `/codex` delegation adapters with standardized task events
- Ollama and OpenAI-compatible model Providers
- Encrypted backups, diagnostics, log redaction, and security regression tests

Hermes delegation is disabled by default while WhiteNight's native tool layer is being expanded.
Set `hermes_enabled: true` only when the Hermes gateway is intentionally configured. Codex is
invoked only by starting a message with `/codex`; ordinary coding requests stay in WhiteNight.

The current distribution targets macOS and QQ through OneBot/NapCat. Its channel and Provider
boundaries are deliberately kept replaceable so that broader chat-platform coverage and support
for additional operating systems can be introduced incrementally without changing the core
conversation, memory, policy, and personality model.

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

The API key must be stored in macOS Keychain under the configured service and account. The Dashboard can write it to Keychain through a password field; it never displays or persists the key. In the Model Provider card, the “Fetch” button queries the selected Provider for available models (`/api/tags` for Ollama or `/models` for OpenAI-compatible APIs) so the model can be selected instead of typed manually. Do not place the key in YAML, logs, or Git. Provider changes apply immediately to new requests and are persisted. The Dashboard can restart a launchd-managed WhiteNight service without using a terminal. See [config/whitenight.yaml.example](config/whitenight.yaml.example) for the full example configuration.

When proactive messaging is enabled, `proactive_sender: qq` sends private messages to the first configured `qq_owner_ids`. Delivery auditing stores only timestamp, target, result, retry count and a message length/hash; normal chat messages are not copied into the security audit table.

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
