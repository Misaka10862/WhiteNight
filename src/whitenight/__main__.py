"""WhiteNight 服务入口。

用法：
    uv run whitenight
    uv run python -m whitenight
"""

from __future__ import annotations

import uvicorn

from whitenight.api.app import create_app
from whitenight.config import load_settings


def main() -> None:
    settings = load_settings()
    settings.ensure_dirs()
    app = create_app(settings)
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        access_log=False,
    )


if __name__ == "__main__":
    main()
