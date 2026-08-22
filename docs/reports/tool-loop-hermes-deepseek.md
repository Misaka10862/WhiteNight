# Tool Loop and Hermes DeepSeek Contract (2026-08-22)

## Runtime contracts

- Local model tools use provider-native structured tool calls. Model text and terminal output are
  never parsed as executable commands.
- File operations pass through `ToolRegistry -> PolicyEngine -> ApprovalService -> ToolExecutor`.
  Read-only operations run automatically; state-changing operations retain their configured
  approval level. Provider-native calls emitted in one turn execute concurrently and their results
  are returned to the model in call order.
- Pending tool calls bind the session, channel, target, canonical parameters and SHA-256 parameter
  digest. File writes/moves/trash operations additionally bind the pre-approval file state.
- `channel.file.send` is only advertised for trusted OneBot requests. It runs without a second
  confirmation while still binding the server-supplied recipient and revalidating path, size and
  SHA-256 immediately before upload.

## Hermes dependency decision

| Dependency | Version / revision | License | Conclusion |
|---|---|---|---|
| Hermes Agent | 0.17.0 / `2f5950a83a66d2b91918bb78e6d1b60f3f48b938` | MIT | Compatible; JSON-RPC `/api/ws` contract pinned by tests |
| websockets | 17.0.1 | BSD-3-Clause | Compatible; direct runtime dependency for the Hermes Gateway client |

Hermes is started as a WhiteNight-owned child process on loopback. The DeepSeek credential is read
from macOS Keychain and injected only into that child process environment. WhiteNight never calls
Hermes `secret.respond`, because Hermes persists that value to its own `.env` file.

Default Hermes inference configuration:

- Provider: `deepseek`
- Base URL: `https://api.deepseek.com/v1` (Hermes built-in provider profile)
- Model: `deepseek-v4-flash-vision-exp`

If port 9119 is already occupied by a process WhiteNight did not start, WhiteNight reports the
conflict and does not connect to or terminate that process.
