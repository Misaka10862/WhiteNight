"""Metadata-only process and task probes for local stability monitoring."""

import asyncio
import os

from whitenight.delegates.manager import TaskStore


async def monitor_snapshot(tasks: TaskStore) -> dict[str, object]:
    rss: int | None = None
    try:
        process = await asyncio.create_subprocess_exec(
            "/bin/ps",
            "-o",
            "rss=",
            "-p",
            str(os.getpid()),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        output, _ = await asyncio.wait_for(process.communicate(), timeout=2)
        if process.returncode == 0:
            rss = int(output.strip()) * 1024
    except (OSError, ValueError, TimeoutError):
        pass
    return {"pid": os.getpid(), "rss_bytes": rss, **tasks.activity_snapshot()}
