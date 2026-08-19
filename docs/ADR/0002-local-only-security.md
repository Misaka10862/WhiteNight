# ADR-0002: Local Priority Security Boundary - Local Listening, Keychain and Encrypted Storage

- Status: Accepted
- Date: 2026-08-15

## Background

Section 9 of the build plan requires: WebUI and services only listen on `127.0.0.1`; keys only enter macOS Keychain;
Local single-user use of SQLite WAL + SQLCipher; any document or web directive must not override system constraints.

## decision making

1. **Network Boundary**: API default binding `127.0.0.1`; CORS only passes
   `http://127.0.0.1:5173` and `http://localhost:5173` (Vite development source).
   LAN/public network access is specifically excluded.
2. **Credentials**: The database master key and service credentials are accessed through the `credentials.keychain` interface.
   Generic password entry for `/usr/bin/security` for production backend; `memory` backend for test/CI only.
   The emergency recovery process allows the `WHITENIGHT_DATABASE_KEY` environment variable, but disables disk writes and logs.
3. **Storage**: `sqlite://` is used for development/testing; `sqlcipher://` is the production database,
   The master key is injected via the PRAGMA parameter and is never written to the connection string. Key driver `sqlcipher3`
   (0.6.2+ provides macOS arm64 cp312 wheel) installed as an optional extra.
4. **Log**: The root logger uniformly mounts desensitization filters, covering token/secret/password/authorization
   and other forms; the production log can switch JSON lines.
5. **Untrusted input**: Chat content, attachments, web pages and documents can never be modified Settings,
   SOUL/AGENTS rule or permission engine; the corresponding defense line is enforced by the policy package in subsequent stages.

## Consequences

- Advantages: Meet local priority and credential non-distribution requirements from the first day.
- Cost: SQLCipher's build/upgrade relies on additional testing; Keychain must use an in-memory backend or mock in CI.
- Fallback: If `sqlcipher3` becomes invalid in the new version of macOS, replace it with the SQLite file-level encryption layer.
  `storage.engine` external interface remains unchanged.

## Revision history

- 2026-08-15 (Phase 1 verification): `sqlcipher3-binary` selected for the first version is only released for Linux
wheel, macOS installation failed; measured `sqlcipher3>=0.6.2` provides macOS arm64 cp312
  wheel and the encrypted read-write prototype passes, so the optional dependency is switched to `sqlcipher3`.
