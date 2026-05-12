import asyncio
import contextlib
import logging
import os
import resource
import signal
import sys
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from creator_service.db import close_pool
from fastapi import FastAPI

logger = logging.getLogger(__name__)


@dataclass
class ShutdownState:
    is_shutting_down: bool = False
    inflight_requests: int = 0


shutdown_state = ShutdownState()


def _parse_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        parsed = int(raw)
    except ValueError:
        logger.warning("Invalid %s=%r; using default %d", name, raw, default)
        return default
    if parsed <= 0:
        logger.warning("Non-positive %s=%r; using default %d", name, raw, default)
        return default
    return parsed


MAX_MEMORY_MB = _parse_int_env("MAX_MEMORY_MB", 1024)
MAX_CPU_PERCENT = _parse_int_env("MAX_CPU_PERCENT", 80)
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")


def _apply_resource_limits() -> None:
    memory_limit_bytes = MAX_MEMORY_MB * 1024 * 1024
    try:
        resource.setrlimit(resource.RLIMIT_AS, (memory_limit_bytes, memory_limit_bytes))
    except (OSError, ValueError):
        logger.error(
            "Failed to set RLIMIT_AS to %d bytes during startup",
            memory_limit_bytes,
            exc_info=True,
        )
        raise


def _cpu_usage_percent(
    previous_cpu_seconds: float, previous_wall_seconds: float
) -> tuple[float, float, float]:
    current_cpu_seconds = (
        resource.getrusage(resource.RUSAGE_SELF).ru_utime
        + resource.getrusage(resource.RUSAGE_SELF).ru_stime
    )
    current_wall_seconds = time.monotonic()
    cpu_delta = max(0.0, current_cpu_seconds - previous_cpu_seconds)
    wall_delta = max(1e-6, current_wall_seconds - previous_wall_seconds)
    cpu_percent = (cpu_delta / wall_delta) * 100.0
    return cpu_percent, current_cpu_seconds, current_wall_seconds


async def _monitor_cpu_limit() -> None:
    cpu_seconds = (
        resource.getrusage(resource.RUSAGE_SELF).ru_utime
        + resource.getrusage(resource.RUSAGE_SELF).ru_stime
    )
    wall_seconds = time.monotonic()
    while True:
        await asyncio.sleep(2.0)
        cpu_percent, cpu_seconds, wall_seconds = _cpu_usage_percent(cpu_seconds, wall_seconds)
        if cpu_percent > float(MAX_CPU_PERCENT):
            logger.error(
                "CPU usage %.1f%% exceeded MAX_CPU_PERCENT=%d; enabling shutdown guard",
                cpu_percent,
                MAX_CPU_PERCENT,
            )
            _mark_shutdown()
            try:
                os.kill(os.getpid(), signal.SIGTERM)
            except OSError:
                logger.warning("SIGTERM delivery failed; falling back to sys.exit(1)")
                sys.exit(1)


def _mark_shutdown() -> None:
    if shutdown_state.is_shutting_down:
        return
    shutdown_state.is_shutting_down = True
    logger.info("Graceful shutdown initiated; draining in-flight requests")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    shutdown_state.is_shutting_down = False
    shutdown_state.inflight_requests = 0
    _apply_resource_limits()
    logger.info(
        "Resource limits configured: MAX_MEMORY_MB=%d, MAX_CPU_PERCENT=%d",
        MAX_MEMORY_MB,
        MAX_CPU_PERCENT,
    )
    cpu_monitor_task = asyncio.create_task(_monitor_cpu_limit())
    yield
    _mark_shutdown()
    cpu_monitor_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await cpu_monitor_task
    await close_pool()
