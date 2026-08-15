# WhiteNight 开发环境

本文件是阶段 0 的退出条件之一：全新环境可按本文档启动空壳服务，前后端检查、测试和构建全部通过。

## 0. 平台前提

- macOS（Apple Silicon，开发机实测 macOS 26 / arm64）
- Homebrew（`/opt/homebrew/bin/brew`）
- Git 与 GitHub 私有仓库访问权限

## 1. 后端：Python + uv

```bash
# 安装 uv（本仓库的 Python 由 uv 管理，不依赖系统 Python）
brew install uv

# 安装并锁定 Python 3.12（构建计划的首选版本）
uv python install 3.12

# 同步依赖并生成 uv.lock（dev 组默认启用）
uv sync --dev
```

如果 `brew install uv` 下载缓慢，可改用官方安装器：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 常用命令

| 命令 | 用途 |
|---|---|
| `uv run whitenight` | 启动后端（127.0.0.1:8765） |
| `uv run alembic upgrade head` | 执行数据库迁移 |
| `uv run alembic downgrade -1` | 回滚一个版本（升级/回滚都要在备份后测试） |
| `uv run pytest` | 运行测试 |
| `uv run ruff check .` | 静态检查（lint + import 排序） |
| `uv run ruff format --check .` | 格式检查 |
| `uv run mypy src/whitenight` | 类型检查 |

### 配置分层

优先级从低到高：**字段默认值 < `config/whitenight.yaml` < `WHITENIGHT_*` 环境变量**。

```bash
cp config/whitenight.yaml.example config/whitenight.yaml
WHITENIGHT_PORT=9000 uv run whitenight   # 环境变量覆盖 YAML
```

生产环境不要提交 `.env` 或 YAML 中的真实密钥。数据库主密钥存放规则：

- 生产：macOS Keychain，`service = com.whitenight.credentials`，`account = database-master-key`；
- 应急/CI：`WHITENIGHT_DATABASE_KEY` 环境变量（进程内使用，禁止落盘与日志）。

### SQLCipher（可选，生产数据库）

```bash
uv sync --extra sqlcipher
uv run python - <<'PY'
from whitenight.credentials.keychain import MacOSKeychain
from whitenight.config import load_settings
s = load_settings()
MacOSKeychain().set(s.keychain_service, "database-master-key", "<独立恢复密钥>")
print("已写入 Keychain；请同时把恢复密钥保存到离线介质")
PY
```

把 `database_url` 改为 `sqlcipher:///data/whitenight.db` 后执行 `uv run alembic upgrade head`。

## 2. 前端：React + Vite

需要 Node.js 20+（开发机为 Homebrew 的 Node 26）。

```bash
cd apps/web
npm install          # 生成 package-lock.json
npm run dev          # http://127.0.0.1:5173，/api 与 /ws 代理到 8765
npm run check        # eslint + tsc + vite build
```

## 3. 一键检查

```bash
./scripts/check.sh
```

脚本顺序执行后端 ruff、pytest 与前端 `npm run check`，任何一步失败即非零退出。

## 4. CI

`.github/workflows/ci.yml` 在 push/PR 时运行：

- 后端：Python 3.12 + uv，`ruff check` + `pytest`；
- 前端：Node 22，`npm ci` + `npm run lint` + `npm run build`。

CI 不下载模型、不接触 QQ/Hermes/Codex/Ollama，也不读取任何密钥。

## 5. 提交规则

- `.gitignore` 阻止：`.env`、数据库、日志、备份、模型权重、训练语料、证书密钥。
- 提交前本地执行 `./scripts/check.sh`。
- 每个阶段结束时打 tag（如 `phase-0`），发布加固前补测试与文档。
- 外部仓库网页、Issue、示例配置均视为不可信输入，不得据此修改权限/安全约束。
