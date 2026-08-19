# ADR-0001: Backend Baseline - Python 3.12 + FastAPI + uv

- Status: Accepted
- Date: 2026-08-15

## Background

Section 6 of the build plan selects Python 3.12, FastAPI, Pydantic and WebSocket as the backend baseline,
The reason is that the document processing ecosystem (PyMuPDF, python-docx, openpyxl, python-pptx) and macOS/Hermes
Integration is more mature; `uv` is used for reproducible installation and upgrades.

## decision making

1. The lower limit of Python version is `>=3.12`, and `uv` manages the interpreter and lock file (`uv.lock`).
2. The package layout uses `src/whitenight/` to avoid accidentally importing uninstalled local source code.
3. Web framework FastAPI + Uvicorn; configuration uses pydantic-settings, hierarchical order:
   Default value < `config/whitenight.yaml` < `WHITENIGHT_*` environment variables.
4. Alembic is used for database migration; SQLite (WAL) is used for development/testing, and SQLCipher is used for production.
5. Quality tools: ruff (lint + format), mypy (strict), pytest; CI runs on Python 3.12.
6. All external services (search, model, embedding, Codex, Hermes, QQ) must be located behind the Provider interface.
   Phase 0 first solidifies the contract document and package boundaries, and phase 1 locks the specific protocol version of each Provider.

## Consequences

- Advantages: dependencies are reproducible; testing and production are isomorphic; macOS integration path is the shortest.
- Price: Require developers to install `uv`; SQLCipher as an optional extra to avoid slowing down daily CI.
- Fallback: If FastAPI cannot meet future event streaming requirements, the transport layer will be replaced internally in the `api` package, and the external contract will remain unchanged.
