from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable
import math
from threading import Lock
import time


class RateLimitExceeded(Exception):
    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__("rate limit exceeded")


class InMemoryRateLimiter:
    def __init__(
        self,
        *,
        max_requests: int,
        window_seconds: int = 60,
        now: Callable[[], float] | None = None,
    ) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._now = now or time.time
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str) -> None:
        current_time = self._now()
        window_start = current_time - self.window_seconds

        with self._lock:
            events = self._events[key]
            while events and events[0] <= window_start:
                events.popleft()

            if len(events) >= self.max_requests:
                retry_after = max(1, math.ceil(events[0] + self.window_seconds - current_time))
                raise RateLimitExceeded(retry_after)

            events.append(current_time)
