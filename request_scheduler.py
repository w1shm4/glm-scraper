"""
Request scheduler for rate-limited and concurrency-safe API calls.

Use this scheduler as a single entrypoint for all outbound API requests.
It prevents bursts, caps concurrency, and retries transient failures.
"""

from __future__ import annotations

import asyncio
import os
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

T = TypeVar("T")
_ENV_CACHE: dict[str, str] | None = None


@dataclass(slots=True)
class SchedulerConfig:
    """Runtime behavior for request scheduling."""

    requests_per_second: float = 5.0
    max_concurrency: int = 1
    max_retries: int = 3
    base_backoff_seconds: float = 0.5
    max_jitter_seconds: float = 0.2

    @property
    def min_interval_seconds(self) -> float:
        if self.requests_per_second <= 0:
            return 0.0
        return 1.0 / self.requests_per_second


class RequestScheduler:
    """
    Queues and executes async request callables with:
    - global rate limiting (requests/sec)
    - concurrency limit
    - retry/backoff for transient failures
    """

    def __init__(self, config: SchedulerConfig | None = None) -> None:
        self.config = config or SchedulerConfig()
        self._semaphore = asyncio.Semaphore(self.config.max_concurrency)
        self._rate_lock = asyncio.Lock()
        self._next_allowed_time = 0.0

    async def schedule(
        self,
        request_coro_factory: Callable[[], Awaitable[T]],
        *,
        request_name: str = "request",
    ) -> T:
        """
        Schedule an async request callable.

        The callable should build and return a *new* coroutine each attempt.
        Example:
            await scheduler.schedule(lambda: client.get("/v1/items"))
        """
        attempt = 0
        while True:
            try:
                async with self._semaphore:
                    await self._await_rate_limit_slot()
                    return await request_coro_factory()
            except Exception as exc:  # noqa: BLE001 - caller controls request exceptions
                attempt += 1
                if attempt > self.config.max_retries:
                    raise RuntimeError(
                        f"{request_name} failed after {self.config.max_retries} retries"
                    ) from exc
                await asyncio.sleep(self._compute_backoff(attempt))

    async def _await_rate_limit_slot(self) -> None:
        if self.config.min_interval_seconds <= 0:
            return

        loop = asyncio.get_running_loop()
        async with self._rate_lock:
            now = loop.time()
            if now < self._next_allowed_time:
                await asyncio.sleep(self._next_allowed_time - now)
                now = loop.time()
            self._next_allowed_time = now + self.config.min_interval_seconds

    def _compute_backoff(self, attempt: int) -> float:
        exp = self.config.base_backoff_seconds * (2 ** (attempt - 1))
        jitter = random.uniform(0.0, self.config.max_jitter_seconds)
        return exp + jitter


def _load_env_file(env_path: str = ".env") -> dict[str, str]:
    """
    Lightweight .env loader to avoid extra dependencies.
    """
    env_values: dict[str, str] = {}
    file_path = Path(env_path)
    if not file_path.exists():
        return env_values

    for raw_line in file_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            env_values[key] = value
    return env_values


def get_required_api_key(env_var: str = "Z_API_KEY", env_path: str = ".env") -> str:
    """
    Always resolve API key from .env (or process env fallback).
    """
    global _ENV_CACHE
    if _ENV_CACHE is None:
        _ENV_CACHE = _load_env_file(env_path=env_path)

    api_key = _ENV_CACHE.get(env_var) or os.getenv(env_var)
    if not api_key:
        raise RuntimeError(
            f"Missing API key '{env_var}'. Add it to {env_path} before making requests."
        )
    return api_key


def create_default_scheduler() -> RequestScheduler:
    """
    Default scheduler tuned for fragile APIs.

    Override values as needed per environment.
    """
    return RequestScheduler(
        SchedulerConfig(
            requests_per_second=3.0,
            max_concurrency=1,
            max_retries=4,
            base_backoff_seconds=0.6,
            max_jitter_seconds=0.25,
        )
    )


DEFAULT_SCHEDULER = create_default_scheduler()


async def schedule_request(
    request_coro_factory: Callable[[], Awaitable[T]],
    *,
    request_name: str = "request",
) -> T:
    """
    Convenience function to enforce scheduler usage everywhere.
    """
    return await DEFAULT_SCHEDULER.schedule(
        request_coro_factory,
        request_name=request_name,
    )


async def schedule_api_request(
    request_coro_factory: Callable[[str], Awaitable[T]],
    *,
    request_name: str = "api_request",
    api_key_env_var: str = "Z_API_KEY",
    env_path: str = ".env",
) -> T:
    """
    Schedule API requests with an API key loaded from .env.

    The request callable receives the API key string.
    Example:
        await schedule_api_request(
            lambda api_key: client.get("/v1/items", headers={"x-api-key": api_key})
        )
    """
    api_key = get_required_api_key(env_var=api_key_env_var, env_path=env_path)
    return await schedule_request(
        lambda: request_coro_factory(api_key),
        request_name=request_name,
    )
