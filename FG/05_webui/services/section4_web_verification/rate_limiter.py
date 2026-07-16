from __future__ import annotations

import asyncio
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Awaitable, Callable, Iterator, TypeVar

from .config import Section4Config


T = TypeVar("T")


class CircuitOpenError(RuntimeError):
    def __init__(self, domain: str, retry_after_seconds: float) -> None:
        self.domain = domain
        self.retry_after_seconds = max(0.0, retry_after_seconds)
        super().__init__(
            f"Circuit is open for {domain}; retry after "
            f"{self.retry_after_seconds:.3f} seconds"
        )


class DailyRequestLimitError(RuntimeError):
    def __init__(self, domain: str, limit: int) -> None:
        self.domain = domain
        self.limit = max(1, int(limit))
        super().__init__(f"Daily request limit reached for {domain}")


@dataclass
class _DomainState:
    semaphore: asyncio.Semaphore
    pacing_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    state_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    next_allowed_at: float = 0.0
    consecutive_failures: int = 0
    circuit_open_until: float = 0.0
    request_day: str = ""
    requests_today: int = 0


@dataclass
class _SyncDomainState:
    semaphore: threading.Semaphore
    pacing_lock: threading.Lock = field(default_factory=threading.Lock)
    state_lock: threading.Lock = field(default_factory=threading.Lock)
    next_allowed_at: float = 0.0
    consecutive_failures: int = 0
    circuit_open_until: float = 0.0
    request_day: str = ""
    requests_today: int = 0


def _utc_day_key() -> str:
    return datetime.now(timezone.utc).date().isoformat()


class DomainRateLimiter:
    """Polite async access control isolated by exact normalized hostname."""

    def __init__(
        self,
        config: Section4Config,
        *,
        base_backoff_seconds: float = 0.25,
        max_backoff_seconds: float = 4.0,
        max_attempts: int = 3,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], Awaitable[Any]] | None = None,
        day_key: Callable[[], str] | None = None,
    ) -> None:
        self.max_concurrent = max(1, int(config.max_concurrent_per_domain))
        requests_per_second = max(0.001, float(config.requests_per_second_per_domain))
        self.min_interval_seconds = 1.0 / requests_per_second
        self.failure_threshold = max(1, int(config.circuit_failure_threshold))
        self.daily_request_limit = max(
            1,
            int(getattr(config, "max_requests_per_domain_per_day", 2_000)),
        )
        self.cooldown_seconds = max(0.0, float(config.circuit_cooldown_seconds))
        self.base_backoff_seconds = max(0.0, float(base_backoff_seconds))
        self.max_backoff_seconds = max(
            self.base_backoff_seconds,
            float(max_backoff_seconds),
        )
        self.max_attempts = max(1, min(5, int(max_attempts)))
        self._clock = clock or time.monotonic
        self._sleep = sleep or asyncio.sleep
        self._day_key = day_key or _utc_day_key
        self._states: dict[str, _DomainState] = {}
        self._states_lock = asyncio.Lock()

    @staticmethod
    def normalize_domain(domain: str) -> str:
        value = str(domain or "").strip().casefold().rstrip(".")
        if (
            not value
            or "://" in value
            or any(character in value for character in ":/\\@?#")
            or any(character.isspace() for character in value)
            or value.startswith(".")
            or ".." in value
        ):
            raise ValueError("An exact hostname is required for rate limiting")
        return value

    async def _state_for(self, domain: str) -> tuple[str, _DomainState]:
        normalized = self.normalize_domain(domain)
        async with self._states_lock:
            state = self._states.get(normalized)
            if state is None:
                state = _DomainState(asyncio.Semaphore(self.max_concurrent))
                self._states[normalized] = state
        return normalized, state

    async def _check_circuit(self, domain: str, state: _DomainState) -> None:
        async with state.state_lock:
            now = float(self._clock())
            if state.circuit_open_until and now < state.circuit_open_until:
                raise CircuitOpenError(domain, state.circuit_open_until - now)
            if state.circuit_open_until and now >= state.circuit_open_until:
                state.circuit_open_until = 0.0
                state.consecutive_failures = 0

    async def record_success(self, domain: str) -> None:
        _, state = await self._state_for(domain)
        async with state.state_lock:
            state.consecutive_failures = 0
            state.circuit_open_until = 0.0

    async def record_failure(self, domain: str) -> None:
        _, state = await self._state_for(domain)
        async with state.state_lock:
            state.consecutive_failures += 1
            if state.consecutive_failures >= self.failure_threshold:
                state.circuit_open_until = float(self._clock()) + self.cooldown_seconds

    async def _reserve_daily_request(self, domain: str, state: _DomainState) -> None:
        day = str(self._day_key())
        async with state.state_lock:
            if state.request_day != day:
                state.request_day = day
                state.requests_today = 0
            if state.requests_today >= self.daily_request_limit:
                raise DailyRequestLimitError(domain, self.daily_request_limit)
            state.requests_today += 1

    def backoff_delay(self, failed_attempt: int, *, retry_after: float | None = None) -> float:
        exponent = max(0, min(10, int(failed_attempt) - 1))
        delay = self.base_backoff_seconds * (2**exponent)
        if retry_after is not None:
            delay = max(delay, max(0.0, float(retry_after)))
        return min(self.max_backoff_seconds, delay)

    @asynccontextmanager
    async def slot(self, domain: str) -> AsyncIterator[None]:
        normalized, state = await self._state_for(domain)
        await self._check_circuit(normalized, state)
        await state.semaphore.acquire()
        try:
            await self._check_circuit(normalized, state)
            await self._reserve_daily_request(normalized, state)
            async with state.pacing_lock:
                now = float(self._clock())
                delay = max(0.0, state.next_allowed_at - now)
                if delay:
                    await self._sleep(delay)
                started_at = float(self._clock())
                state.next_allowed_at = max(state.next_allowed_at, started_at) + (
                    self.min_interval_seconds
                )

            try:
                yield
            except Exception:
                await self.record_failure(normalized)
                raise
            else:
                await self.record_success(normalized)
        finally:
            state.semaphore.release()

    async def run(
        self,
        domain: str,
        operation: Callable[[], Awaitable[T]],
        *,
        max_attempts: int | None = None,
        retry_if: Callable[[Exception], bool] | None = None,
    ) -> T:
        attempts = self.max_attempts if max_attempts is None else max(
            1,
            min(self.max_attempts, int(max_attempts)),
        )
        should_retry = retry_if or (lambda _error: True)

        for attempt in range(1, attempts + 1):
            try:
                async with self.slot(domain):
                    return await operation()
            except CircuitOpenError:
                raise
            except Exception as error:
                if attempt >= attempts or not should_retry(error):
                    raise
                delay = self.backoff_delay(attempt)
                if delay:
                    await self._sleep(delay)

        raise RuntimeError("Rate-limited operation exhausted without a result")

    async def snapshot(self, domain: str) -> dict[str, Any]:
        normalized, state = await self._state_for(domain)
        async with state.state_lock:
            now = float(self._clock())
            return {
                "domain": normalized,
                "consecutive_failures": state.consecutive_failures,
                "circuit_open": bool(
                    state.circuit_open_until and state.circuit_open_until > now
                ),
                "retry_after_seconds": max(0.0, state.circuit_open_until - now),
                "min_interval_seconds": self.min_interval_seconds,
                "max_concurrent": self.max_concurrent,
                "request_day": state.request_day or str(self._day_key()),
                "requests_today": state.requests_today,
                "daily_request_limit": self.daily_request_limit,
            }


class SyncDomainRateLimiter:
    """Thread-safe synchronous counterpart used by Flask source adapters."""

    def __init__(
        self,
        config: Section4Config,
        *,
        base_backoff_seconds: float = 0.25,
        max_backoff_seconds: float = 4.0,
        max_attempts: int = 3,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], Any] | None = None,
        day_key: Callable[[], str] | None = None,
    ) -> None:
        self.max_concurrent = max(1, int(config.max_concurrent_per_domain))
        requests_per_second = max(0.001, float(config.requests_per_second_per_domain))
        self.min_interval_seconds = 1.0 / requests_per_second
        self.failure_threshold = max(1, int(config.circuit_failure_threshold))
        self.daily_request_limit = max(
            1,
            int(getattr(config, "max_requests_per_domain_per_day", 2_000)),
        )
        self.cooldown_seconds = max(0.0, float(config.circuit_cooldown_seconds))
        self.base_backoff_seconds = max(0.0, float(base_backoff_seconds))
        self.max_backoff_seconds = max(
            self.base_backoff_seconds,
            float(max_backoff_seconds),
        )
        self.max_attempts = max(1, min(5, int(max_attempts)))
        self._clock = clock or time.monotonic
        self._sleep = sleep or time.sleep
        self._day_key = day_key or _utc_day_key
        self._states: dict[str, _SyncDomainState] = {}
        self._states_lock = threading.Lock()

    @staticmethod
    def normalize_domain(domain: str) -> str:
        return DomainRateLimiter.normalize_domain(domain)

    def _state_for(self, domain: str) -> tuple[str, _SyncDomainState]:
        normalized = self.normalize_domain(domain)
        with self._states_lock:
            state = self._states.get(normalized)
            if state is None:
                state = _SyncDomainState(threading.Semaphore(self.max_concurrent))
                self._states[normalized] = state
        return normalized, state

    def _check_circuit(self, domain: str, state: _SyncDomainState) -> None:
        with state.state_lock:
            now = float(self._clock())
            if state.circuit_open_until and now < state.circuit_open_until:
                raise CircuitOpenError(domain, state.circuit_open_until - now)
            if state.circuit_open_until and now >= state.circuit_open_until:
                state.circuit_open_until = 0.0
                state.consecutive_failures = 0

    def record_success(self, domain: str) -> None:
        _, state = self._state_for(domain)
        with state.state_lock:
            state.consecutive_failures = 0
            state.circuit_open_until = 0.0

    def record_failure(self, domain: str) -> None:
        _, state = self._state_for(domain)
        with state.state_lock:
            state.consecutive_failures += 1
            if state.consecutive_failures >= self.failure_threshold:
                state.circuit_open_until = float(self._clock()) + self.cooldown_seconds

    def _reserve_daily_request(self, domain: str, state: _SyncDomainState) -> None:
        day = str(self._day_key())
        with state.state_lock:
            if state.request_day != day:
                state.request_day = day
                state.requests_today = 0
            if state.requests_today >= self.daily_request_limit:
                raise DailyRequestLimitError(domain, self.daily_request_limit)
            state.requests_today += 1

    def backoff_delay(self, failed_attempt: int, *, retry_after: float | None = None) -> float:
        exponent = max(0, min(10, int(failed_attempt) - 1))
        delay = self.base_backoff_seconds * (2**exponent)
        if retry_after is not None:
            delay = max(delay, max(0.0, float(retry_after)))
        return min(self.max_backoff_seconds, delay)

    @contextmanager
    def slot(self, domain: str) -> Iterator[None]:
        normalized, state = self._state_for(domain)
        self._check_circuit(normalized, state)
        state.semaphore.acquire()
        try:
            self._check_circuit(normalized, state)
            self._reserve_daily_request(normalized, state)
            with state.pacing_lock:
                now = float(self._clock())
                delay = max(0.0, state.next_allowed_at - now)
                if delay:
                    self._sleep(delay)
                started_at = float(self._clock())
                state.next_allowed_at = max(state.next_allowed_at, started_at) + (
                    self.min_interval_seconds
                )

            try:
                yield
            except Exception:
                self.record_failure(normalized)
                raise
            else:
                self.record_success(normalized)
        finally:
            state.semaphore.release()

    def run(
        self,
        domain: str,
        operation: Callable[[], T],
        *,
        max_attempts: int | None = None,
        retry_if: Callable[[Exception], bool] | None = None,
    ) -> T:
        attempts = self.max_attempts if max_attempts is None else max(
            1,
            min(self.max_attempts, int(max_attempts)),
        )
        should_retry = retry_if or (lambda _error: True)

        for attempt in range(1, attempts + 1):
            try:
                with self.slot(domain):
                    return operation()
            except CircuitOpenError:
                raise
            except Exception as error:
                if attempt >= attempts or not should_retry(error):
                    raise
                delay = self.backoff_delay(attempt)
                if delay:
                    self._sleep(delay)

        raise RuntimeError("Rate-limited operation exhausted without a result")

    def snapshot(self, domain: str) -> dict[str, Any]:
        normalized, state = self._state_for(domain)
        with state.state_lock:
            now = float(self._clock())
            return {
                "domain": normalized,
                "consecutive_failures": state.consecutive_failures,
                "circuit_open": bool(
                    state.circuit_open_until and state.circuit_open_until > now
                ),
                "retry_after_seconds": max(0.0, state.circuit_open_until - now),
                "min_interval_seconds": self.min_interval_seconds,
                "max_concurrent": self.max_concurrent,
                "request_day": state.request_day or str(self._day_key()),
                "requests_today": state.requests_today,
                "daily_request_limit": self.daily_request_limit,
            }
