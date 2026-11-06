"""Process-local login throttling; use a shared edge limiter for multiple workers."""
from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable


class LoginLimiter:
    """Fixed windows, counting every attempt including successful logins.

    The global ceiling also prevents bypass by rotating client addresses. Full
    client tables fail closed until entries expire, rather than evicting limits.
    """

    def __init__(
        self, per_client: int = 10, total: int = 100, window: float = 60,
        max_clients: int = 1024, clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if min(per_client, total, window, max_clients) <= 0:
            raise ValueError("Login limits must be positive")
        self.per_client = per_client
        self.total = total
        self.window = window
        self.max_clients = max_clients
        self.clock = clock
        self._lock = threading.Lock()
        self._clients: dict[str, tuple[float, int]] = {}
        self._global: tuple[float, int] | None = None

    def retry_after(self, client: str) -> int:
        """Reserve an attempt atomically; return zero or seconds until retry."""
        with self._lock:
            now = self.clock()
            self._clients = {
                key: value for key, value in self._clients.items()
                if value[0] > now
            }
            if self._global is None or self._global[0] <= now:
                self._global = (now + self.window, 0)
            global_end, global_count = self._global
            client_end, client_count = self._clients.get(client, (now + self.window, 0))
            blocked_until = []
            if global_count >= self.total:
                blocked_until.append(global_end)
            if client_count >= self.per_client:
                blocked_until.append(client_end)
            if client not in self._clients and len(self._clients) >= self.max_clients:
                blocked_until.append(min(end for end, _ in self._clients.values()))
            if blocked_until:
                return max(1, math.ceil(max(blocked_until) - now))
            self._global = (global_end, global_count + 1)
            self._clients[client] = (client_end, client_count + 1)
            return 0
