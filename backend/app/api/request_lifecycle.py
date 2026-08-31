from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from fastapi import Request


T = TypeVar("T")


def require_connected_task() -> None:
    task = asyncio.current_task()
    if task is not None and task.cancelling():
        raise asyncio.CancelledError


async def run_until_disconnect(request: Request, operation: Callable[[], Awaitable[T]]) -> T:
    """Called after FastAPI has consumed/validated the request body."""
    async def watch_disconnect():
        while True:
            message = await request.receive()
            if message["type"] == "http.disconnect":
                return

    work = asyncio.create_task(operation())
    watcher = asyncio.create_task(watch_disconnect())
    try:
        done, _ = await asyncio.wait({work, watcher}, return_when=asyncio.FIRST_COMPLETED)
        if watcher in done:
            raise asyncio.CancelledError
        return await work
    finally:
        for task in (work, watcher):
            if not task.done():
                task.cancel()
        # Join cleanup/rollback. Never shield or continue generation in background.
        await asyncio.gather(work, watcher, return_exceptions=True)
