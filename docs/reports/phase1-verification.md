# Phase 1 High-Risk Capability Actual Measurement Report (2026-08-15)

> Status: In progress. Each capability gives a conclusion of "available/partially available/to be operated by the user/alternative solutions".
>Rerun command: `uv run scripts/verify_phase1.py --smoke-model --smoke-gateway`
> Raw JSON evidence: `data/reports/phase1-*.json` (native data directory, not included in Git).

## 0. Native environment

- macOS 26 (arm64), 16 GiB unified memory, ~348 GiB free disk
- Ollama 0.32.1 (native resident service)
- Python 3.12.14 (uv management); Node v26.4.0; Hermes v0.17.0; Codex CLI 0.147.0

## 1. Local model: Ollama qwen3-vl:8b - available

| projects | qwen3:8b (text) | qwen3-vl:8b (visual) |
|---|---|---|
| Quantization / Size | Q4_K_M / 5.2 GB | Q4_K_M / 6.1 GB |
| Context length | 40 960 | 262 144 |
| Ability | completion, tools, thinking | completion, vision, tools, thinking |

Smoke test results (16 GiB machine, model cold loading, `think` off text model):

| Smoke test | First token | First visible content | Total duration | Output |
|---|---|---|---|---|
| Text "Just two words to reply: OK" | 2.19 s | 2.19 s | 2.23 s | "OK" |
| Visual "Describe the content of this image, in one sentence" (32×32 red PNG) | 8.17 s | 11.54 s | 12.27 s | "This image is filled entirely with a uniform red color, without any other visual elements or details." |
| Tool call "Check Hangzhou Weather" (`get_weather` JSON Schema) | — | — | 3.45 s | `tool_calls[0].arguments == {"city":"Hangzhou"}`, Schema passed |

Conclusion: The performance targets of 5–8 seconds for text chat and 15 seconds for image understanding are established on current hardware.

### Measured conclusions that must be solidified (for use by Provider implementation)

1. **The picture must be hung in the `images` field of the user message**. qwen3-vl for Ollama 0.32
   The top-level `images` field will be silently ignored and the model will say "no images seen".
2. **qwen3-vl current template ignores `think:false`**: always outputs `<think>` reasoning token first,
   Visible content arrives later (approximately 3.4 s longer as measured). Context budget and "first content delay" calculation
   Thinking tokens must be included; if support is turned off in subsequent Ollama versions, rerun the smoke test comparison.
3. The qwen3 text model supports top-level `think:false`, which should be turned off by default to obtain companion instant replies;
   Only routing/structured tasks enable thinking on demand.
4. Only one 8B model resides under 16 GiB: Ollama automatically unloads unused models; scheduling and embedding are loaded on demand.
   It is recommended to configure the concurrency parameters conservatively with `OLLAMA_NUM_PARALLEL=1` first, and then lock them with load testing in phase 2.
5. Tool calls are available: `/api/chat` + `tools` returns structured `tool_calls`, and the parameters conform to JSON Schema
   (Actual test `get_weather(city="Hangzhou")`); The tool execution layer in stage 2 must still verify parameters by the program.
   Model output cannot be performed directly.

## 2. Hermes - partially available (requires user login model Provider)

- Hermes Agent v0.17.0 (upstream 2f5950a8) is installed in `~/.local/bin/hermes`.
- **Gateway smoke test passed**: `hermes serve --host 127.0.0.1 --port <port>` can be automatically built
  WebUI and returns HTTP 200 within a limited time; OpenAPI exposes sessions, files, tools,
  Computer-use, auth and other complete REST aspects.
  - Note: `--skip-build` will exit directly when there is no web dist for the first time. It will be built first and then available.
- **Task-level verification blocked by credentials**: `hermes status` shows that all model providers are not logged in;
  `/api/sessions` returns 401. Requires user to execute `hermes model` / `hermes auth`
  Login to an available Provider to verify session creation, streaming events, approvals, and aborts.
- **computer-use (cua-driver)**: `cua-driver 0.19.3` is installed (successfully downloaded via local agent),
  Located in `~/.local/bin/cua-driver` and `/Applications/CuaDriver.app` (bundle id
  `com.trycua.driver`). `hermes computer-use doctor` results:
  Binaries/platforms/MCP sessions/bundle identities all pass; **Accessibility and screen recording TCC not authorized**,
  UI inspections and event injection are not available. The user needs to set authorization in the system, or run
  `hermes computer-use permissions grant` and confirm in the pop-up system dialog box.
  computer-use cannot perform real GUI operations before authorization, but this does not block Gateway protocol development.
- Alternative: If computer-use does not meet the standards in terms of permissions or stability, the GUI operation Provider can be replaced
(Build Plan Section 19 Risk Table Reserved); Hermes Adapter relies only on the Gateway protocol.

## 3. Codex - available (protocol handshake verified)

- `codex-cli 0.147.0` is installed globally; `~/.codex/auth.json` exists (contents not read).
- **MCP stdio handshake passed**: send JSON-RPC to `codex mcp-server`
  `initialize`(protocolVersion `2025-03-26`), return
  `serverInfo: codex-mcp-server 0.147.0`。
- New/continued threads, working directories, sandboxes and error recovery will be verified with contract testing in stage 5;
  Phase 1 has confirmed that the official MCP entrance is available and there is no need to implement the protocol yourself.

## 4. NapCat / QQ - waiting for user operation

- NapCat is not installed; npm package `napcat` has been officially removed (404), you need to download it from NapCatQQ official website
  The release channel downloads and builds a dedicated QQ account for users to scan the QR code to log in to.
- The blocking point is the interaction between account risk control and QR code scanning, which cannot be done by Agent; OneBot 11 Adapter can be used first
  Mock OneBot server development without blocking.

## 5. SQLCipher + Keychain - available

- The first version of `sqlcipher3-binary` was only released for Linux wheel, and the installation failed on macOS (recorded
  ADR-0002 revision); switch to `sqlcipher3==0.6.2` (provides macOS arm64 cp312 wheel),
  `uv sync --extra sqlcipher` succeeded.
- Actual measurement: Correct keys can be used to write/read tables; incorrect keys are rejected; driver version SQLCipher 3.51.1.
- **Engine layer integration test passed** (`tests/test_sqlcipher_integration.py`, 23 tests all green):
  `storage.engine.build_engine("sqlcipher:///...", key=...)` via PRAGMA key
  Working; `PRAGMA key` does not accept bind parameters, has been changed to escaped literal injection and is not logged.
- macOS Keychain one-time entry write/read/delete probe pass (`security` CLI backend).

## 6. Phase 1 Conclusion and To-Do

| Ability | Conclusion |
|---|---|
| qwen3-vl:8b reasoning | Available, performance meets standards, interface conclusion has been solidified |
| Hermes Gateway | The protocol plane is available; the task link is waiting for the user to log in Provider |
| Hermes computer-use | Driver 0.19.3 installed; TCC authorization awaits user confirmation (doctor has given accurate diagnosis) |
| Codex MCP | Available, handshake passed |
| NapCat / QQ | Waiting for users to download and scan the code; develop available mocks first |
| SQLCipher / Keychain | Available, prototype and integration tests passed |

The exit conditions of "each high-risk capability has available solutions or clear alternatives" have been basically met;
Only the Hermes task link and QQ link require the user to complete the login/scan the QR code and then run a contract smoke test.
Development of Phase 2 (minimum vertical link) is not blocked during this period.
