import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from creator_service.db import isolated_pool

invocation_loop: ContextVar[asyncio.AbstractEventLoop | None] = ContextVar("invocation_loop", default=None)


@contextmanager
def lightweight_worker_context() -> Iterator[None]:
    with asyncio.Runner() as runner, isolated_pool() as pool:
        loop = runner.get_loop()
        token = invocation_loop.set(loop)
        try:
            yield
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            try:
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                loop.run_until_complete(pool.close())
            finally:
                invocation_loop.reset(token)
