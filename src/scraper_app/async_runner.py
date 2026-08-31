"""Running async engine code from a synchronous caller (audit v0.2 section 33).

Streamlit runs each script in a worker thread, and several optional engines are
async. ``asyncio.run`` is the obvious call, but it raises::

    RuntimeError: asyncio.run() cannot be called from a running event loop

whenever the caller already sits inside a loop — which happens as soon as the
app is embedded in an async host, or when one async engine calls another.

:func:`run_async_safely` is the single entry point every engine uses instead. It
runs the work on the current thread when that is safe, and on a dedicated
worker thread with its own loop when it is not.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TypeVar

T = TypeVar("T")

#: What callers may hand us: a coroutine, or a callable that builds one.
AsyncWork = Awaitable[T] | Callable[[], Awaitable[T]]


def _loop_is_running() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def run_async_safely(work: AsyncWork, *, timeout: float | None = None) -> Any:
    """Run ``work`` to completion and return its result.

    ``work`` may be a coroutine or a zero-argument callable returning one. The
    callable form is preferred: if the coroutine has to be re-created on the
    worker thread, only the callable form can do that without the
    "coroutine was never awaited" warning.

    ``timeout`` applies only to the worker-thread path, where a hung engine
    would otherwise block the caller forever.
    """
    if not _loop_is_running():
        coro = work() if callable(work) else work
        return asyncio.run(coro)  # type: ignore[arg-type]

    # A loop already owns this thread. Hand the work to a thread that has none,
    # so the new loop it creates cannot collide with the caller's.
    if callable(work):
        factory = work
    else:
        pending = work

        async def factory_coro() -> Any:
            return await pending

        factory = factory_coro  # type: ignore[assignment]

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="srws-async") as pool:
        future = pool.submit(lambda: asyncio.run(factory()))  # type: ignore[arg-type]
        return future.result(timeout=timeout)
