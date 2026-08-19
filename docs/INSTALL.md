# Installation and first startup

## 1. Prefix

- macOS (tested on Apple Silicon), Homebrew
- Node.js 20+ (WebUI development) with `uv`
- Ollama is installed and the model is pulled: `ollama pull qwen3-vl:8b`
- Optional: `uv sync --extra sqlcipher` (production encryption library), `--extra ocr` (Apple Vision OCR)

## 2. Installation

```bash
git clone <private warehouse address> WhiteNight
cd WhiteNight
brew install uv || curl -LsSf https://astral.sh/uv/install.sh | sh
uv python install 3.12
uv sync --dev
uv run alembic upgrade head
cp config/whitenight.yaml.example config/whitenight.yaml
```

## 3. First startup

```bash
uv run whitenight # http://127.0.0.1:8765, automatic migration
cd apps/web && npm install && npm run dev   # http://127.0.0.1:5173
```

Open WebUI → Model page to confirm Ollama health; chat page sends "Hello" verification link.

## 4. System permissions (granted on demand)

| Capabilities | System Settings Location | Description |
|---|---|---|
| Screenshots | Privacy & Security → Screen Recording | Grant Terminal/whitenight |
| GUI Operations (Hermes) | Accessibility + Screen Recording | `hermes computer-use permissions grant` |
| Trash deletion | Automation (Finder) | macOS will prompt when executing for the first time |
| Background auto-start | Login items | `./scripts/install_launchd.sh --install` |

## 5. QQ configuration

1. Download and build from NapCatQQ official channel, scan the QR code to log in to the dedicated QQ account.
2. Configure OneBot HTTP to report to `http://127.0.0.1:8765/api/v1/onebot/events`.
3. Set in `config/whitenight.yaml`:

```yaml
qq_enabled: true
qq_owner_ids: [your QQ number]
qq_onebot_api_url: http://127.0.0.1:3000
```

4. Restart WhiteNight and confirm the QQ/OneBot status on the model page.

## 6. Backup recovery key

```bash
uv run scripts/backup.py generate-key # Save offline after printing
uv run scripts/backup.py backup --output data/backups/whitenight.bak
uv run scripts/backup.py preview --input data/backups/whitenight.bak
```

Stop the service before restoring: `uv run scripts/backup.py restore --input data/backups/whitenight.bak`
