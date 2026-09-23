from collections.abc import Callable, Coroutine
from functools import wraps
from typing import ParamSpec, TypeVar

import anyio
from anyio.lowlevel import RunVar

P = ParamSpec("P")
T = TypeVar("T")
class BlockingIO:
    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self._limiter: RunVar[anyio.CapacityLimiter] = RunVar("blocking_io_limiter")

    async def run(self, function: Callable[[], T]) -> T:
        try:
            limiter = self._limiter.get()
        except LookupError:
            limiter = anyio.CapacityLimiter(self.capacity)
            self._limiter.set(limiter)
        return await anyio.to_thread.run_sync(function, limiter=limiter, abandon_on_cancel=False)


run_blocking = BlockingIO(8).run
run_control = BlockingIO(4).run
run_admin_limiter = BlockingIO(1).run


def owned_operation(function: Callable[P, Coroutine[None, None, T]]) -> Callable[P, Coroutine[None, None, T]]:
    @wraps(function)
    async def complete(*args: P.args, **kwargs: P.kwargs) -> T:
        await anyio.lowlevel.checkpoint()
        # Cancellation cannot release a reservation while its publish still runs.
        with anyio.CancelScope(shield=True):
            return await function(*args, **kwargs)
    return complete
