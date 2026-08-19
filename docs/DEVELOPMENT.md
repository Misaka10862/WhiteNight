#WhiteNight Development Environment

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

# Synchronize dependencies and generate uv.lock (enabled by default in dev group)
uv sync --dev
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
- Emergency/CI: `WHITENIGHT_DATABASE_KEY` environment variable (used within the process, disk placement and logging are prohibited).

### SQLCipher (optional, production database)

```bash
uv sync --extra sqlcipher
uv run python - <<'PY'
from whitenight.credentials.keychain import MacOSKeychain
from whitenight.config import load_settings
s = load_settings()
MacOSKeychain().set(s.keychain_service, "database-master-key", "<independent recovery key>")
print("Written to Keychain; please save the recovery key to offline media at the same time")
PY
```

Change `database_url` to `sqlcipher:///data/whitenight.db` and then execute `uv run alembic upgrade head`.

### Apple Vision OCR (optional, images and scanned PDFs)

```bash
uv sync --extra ocr
```

Valid only on macOS; document parsing returns clear errors for images when not installed instead of fake content.

## 2. Front-end: React + Vite

Requires Node.js 20+ (development machine is Node 26 with Homebrew).

```bash
cd apps/web
npm install # Generate package-lock.json
npm run dev # http://127.0.0.1:5173, /api and /ws proxy to 8765
npm run check        # eslint + tsc + vite build
```

## 3. One-click check

```bash
./scripts/check.sh
```

The script sequentially executes back-end ruff, pytest and front-end `npm run check`. If any step fails, it will exit non-zero.

## 4. CI

`.github/workflows/ci.yml` is run when pushing/PRing:

- Backend: Python 3.12 + uv, `ruff check` + `pytest`;
- Frontend: Node 22, `npm ci` + `npm run lint` + `npm run build`.

CI does not download models, does not touch QQ/Hermes/Codex/Ollama, and does not read any keys.

## 5. Submit rules

- `.gitignore` blocks: `.env`, database, logs, backups, model weights, training corpus, certificate keys.
- Execute `./scripts/check.sh` locally before submitting.
- Tag at the end of each phase (such as `phase-0`), and supplement testing and documentation before releasing the reinforcement.
- External warehouse web pages, issues, and sample configurations are considered untrusted input, and permissions/security constraints must not be modified accordingly.

## 6. Known operational issues

- **Pushing commits containing `.github/workflows` is rejected**: GitHub's OAuth credentials require `workflow`
  scope. Repair and try again:

  ```bash
  gh auth refresh -s workflow
  git push -u origin main
  ```

Local commits and tags are not affected; do not delete the CI configuration to accommodate the old credentials until the credentials are repaired.
