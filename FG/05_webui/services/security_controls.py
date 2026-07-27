"""Small dependency-free security controls shared by the Flask application.

These controls deliberately remain process-local. They provide a safe baseline
for a single application instance; production replicas should use a shared
rate-limit/session backend such as Redis.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    retry_after_seconds: int


class SlidingWindowRateLimiter:
    """Thread-safe sliding-window limiter with bounded opportunistic cleanup."""

    def __init__(self, *, max_keys: int = 20_000, clock=time.monotonic):
        self.max_keys = max(100, int(max_keys))
        self.clock = clock
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str, *, limit: int, window_seconds: int) -> RateLimitDecision:
        limit = max(1, int(limit))
        window_seconds = max(1, int(window_seconds))
        now = float(self.clock())
        cutoff = now - window_seconds

        with self._lock:
            events = self._events[str(key)]
            while events and events[0] <= cutoff:
                events.popleft()

            if len(events) >= limit:
                retry_after = max(1, int(window_seconds - (now - events[0]) + 0.999))
                return RateLimitDecision(False, 0, retry_after)

            events.append(now)
            remaining = max(0, limit - len(events))

            # Bound memory if a hostile client generates many unique keys.
            if len(self._events) > self.max_keys:
                stale_keys = [
                    item_key
                    for item_key, item_events in list(self._events.items())[:1000]
                    if not item_events or item_events[-1] <= cutoff
                ]
                for stale_key in stale_keys:
                    self._events.pop(stale_key, None)

            return RateLimitDecision(True, remaining, 0)

