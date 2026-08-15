# ADR-0001：后端基线 —— Python 3.12 + FastAPI + uv

- 状态：已接受
- 日期：2026-08-15

## 背景

构建计划第 6 节选定 Python 3.12、FastAPI、Pydantic 与 WebSocket 作为后端基线，
原因是文档处理生态（PyMuPDF、python-docx、openpyxl、python-pptx）与 macOS/Hermes
集成都更成熟；`uv` 用于可复现安装与升级。

## 决策

1. Python 版本下限 `>=3.12`，由 `uv` 管理解释器与锁文件（`uv.lock`）。
2. 包布局采用 `src/whitenight/`，避免意外导入未安装的本地源码。
3. Web 框架 FastAPI + Uvicorn；配置使用 pydantic-settings，分层顺序：
   默认值 < `config/whitenight.yaml` < `WHITENIGHT_*` 环境变量。
4. 数据库迁移使用 Alembic；开发/测试用 SQLite（WAL），生产用 SQLCipher。
5. 质量工具：ruff（lint + format）、mypy（strict）、pytest；CI 在 Python 3.12 上运行。
6. 所有外部服务（搜索、模型、嵌入、Codex、Hermes、QQ）都必须位于 Provider 接口之后，
   阶段 0 先固化契约文档与包边界，阶段 1 锁定各 Provider 的具体协议版本。

## 后果

- 优点：依赖可复现；测试与生产同构；macOS 集成路径最短。
- 代价：要求开发者安装 `uv`；SQLCipher 作为可选 extra，避免拖慢日常 CI。
- 回退：如 FastAPI 无法满足未来事件流需求，`api` 包内部替换传输层，对外契约不变。
