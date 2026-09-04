# WhiteNight development environment

This document is one of the exit conditions for phase 0: the new environment can start the shell service according to this document, and the front-end and back-end inspection, testing and construction all pass.

## 0. Platform premise

- macOS (Apple Silicon, development machine tested macOS 26/arm64)
- Homebrew（`/opt/homebrew/bin/brew`）
- Git and GitHub private repository access

## 1. Backend: Python + uv

```bash
# Install uv (Python in this repository is managed by uv and does not depend on system Python)
brew install uv

# Install and lock Python 3.12 (preferred version for build plans)
uv python install 3.12

# Install the recorded dependency set; dependency updates are a separate reviewed change
uv sync --locked --dev --extra sqlcipher
```

If `brew install uv` downloads slowly, you can use the official installer instead:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Common commands

| Command | Purpose |
|---|---|
| `uv run whitenight` | Start backend (127.0.0.1:8765) |
| `uv run alembic upgrade head` | Perform database migration |
| `uv run alembic downgrade -1` | Roll back a version (upgrade/rollback must be tested after backup) |
| `uv run pytest` | Run test |
| `uv run ruff check .` | Static check (lint + import sorting) |
| `uv run ruff format --check .` | Format check |
| `uv run mypy src/whitenight` | Type checking |

### Configure layering

Priority from low to high: **Field default value < `config/whitenight.yaml` < `WHITENIGHT_*` environment variable**.

```bash
cp config/whitenight.yaml.example config/whitenight.yaml
WHITENIGHT_PORT=9000 uv run whitenight # Environment variable override YAML
```

Do not submit real keys in `.env` or YAML for production. Database master key storage rules:

- Production: macOS Keychain, `service=com.whitenight.credentials`, `account=database-master-key`;
- Tests: isolated temporary databases and synthetic in-memory credentials; production keys are never copied into test fixtures, shell history or configuration.

### SQLCipher (optional, production database)

```bash
uv sync --extra sqlcipher
uv run python - <<'PY'
from getpass import getpass
from whitenight.credentials.keychain import MacOSKeychain
from whitenight.config import load_settings
s = load_settings()
key = getpass("Database master key: ")
if not key:
    raise SystemExit("A database key is required")
MacOSKeychain().set(s.keychain_service, "database-master-key", key)
print("Database key stored in Keychain")
PY
```

Change `database_url` to `sqlcipher:///data/whitenight.db` and then execute `uv run alembic upgrade head`.

### Apple Vision OCR (optional, images and scanned PDFs)

```bash
uv sync --extra ocr
```

Valid only on macOS; document parsing returns clear errors for images when not installed instead of fake content.

## 2. Front-end: React + Vite

The installed Vite 7 requires Node.js 20.19+ on the Node 20 line, or Node.js 22.12+ (the development machine uses Node 26).

```bash
cd apps/web
npm install # Install the existing locked dependency set
npm run dev # http://127.0.0.1:5173, /api and /ws proxy to 8765
npm run check        # eslint + node:test behavior checks + tsc + vite build
```

For a persistent local development service, install the user-level launchd job:

```bash
./scripts/install_webui_launchd.sh --install
./scripts/install_webui_launchd.sh --status
```

## 3. One-click check

```bash
./scripts/check.sh
```

The script runs Ruff checks, strict mypy, the tracked-secret scan, pytest, frontend behavior/static/build checks and the technical-English audit. It exits non-zero on failure and does not install dependencies. Install the locked environment separately before running it.

## 4. Local verification

GitHub Actions is disabled for this repository. The previous workflow did not start because the
GitHub account was locked by a billing issue; no backend, web, or secret-scan step executed. Run
`./scripts/check.sh` before every push. It covers backend lint/type/tests, frontend behavior/lint/build, a
tracked-file credential scan, and the technical-English audit without downloading models or
reading credential stores.

## 5. Submit rules

- `.gitignore` blocks: `.env`, database, logs, backups, model weights, training corpus, certificate keys.
- Execute `./scripts/check.sh` locally before submitting.
- Run `./scripts/install_git_hooks.sh` once per clone. The versioned commit hook rejects CJK
  characters in commit subjects; commit bodies may still contain Chinese.
- Tag at the end of each phase (such as `phase-0`), and supplement testing and documentation before releasing the reinforcement.
- External warehouse web pages, issues, and sample configurations are considered untrusted input, and permissions/security constraints must not be modified accordingly.

## 6. Hosted automation status

- Repository Actions permission: disabled by project decision on 2026-08-22.
- Local verification remains mandatory through `./scripts/check.sh`.
- Re-enabling hosted automation requires an explicit project decision and a resolved GitHub billing state.

## 7. Repeatable browser acceptance

Use `scripts/browser_fixture.py` to create a disposable SQLite database and deterministic slow
Provider. It disables QQ, proactive messages and Hermes, uses synthetic in-memory credentials, and
binds the API to port 8769. Production ports 8765/5173 are not used for this acceptance fixture.

```bash
.venv/bin/python scripts/browser_fixture.py
# In another terminal:
WHITENIGHT_API_URL=http://127.0.0.1:8769 npm --prefix apps/web run dev -- --host 127.0.0.1 --port 5179 --strictPort
```

Open `http://127.0.0.1:5179` in the test browser. The fixture seeds A/B sessions and two safe
approval records. Check one-time versus session grants, changing sessions/pages during generation,
stopping a reply, provider failure, document upload, backup creation/verification/preview, and a
narrow viewport. IME confirmation is covered by a deterministic client test; record a real input-method
check separately when available. Stop only the fixture processes after acceptance; temporary data is retained.
No new frontend test dependencies are required: node:test reuses the existing TypeScript compiler.

Maintenance and recovery architecture is documented in ADR-0005 and `docs/OPERATIONS.md`.
