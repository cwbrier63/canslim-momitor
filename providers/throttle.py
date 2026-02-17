"""
CANSLIM Monitor - Token-Bucket Rate Limiter
============================================
Thread-safe rate limiter that enforces:
  - Sustained rate via token bucket (calls_per_minute)
  - Burst allowance (burst_size extra tokens)
  - Minimum inter-call delay (min_delay_seconds)
  - Exponential back-off on 429 responses

Usage:
    from canslim_monitor.providers.types import ThrottleProfile
    from canslim_monitor.providers.throttle import RateLimiter

    limiter = RateLimiter(ThrottleProfile(calls_per_minute=5, min_delay_seconds=0.5))
    limiter.acquire()   # blocks until a call is allowed
    response = api_call()
    if response.status_code == 429:
        limiter.report_429()
    else:
        limiter.report_success()
"""

import time
import threading
import logging

from canslim_monitor.providers.types import ThrottleProfile


class RateLimiter:
    """Token-bucket rate limiter with 429 exponential back-off."""

    def __init__(self, profile: ThrottleProfile, logger: logging.Logger = None):
        self._profile = profile
        self._logger = logger or logging.getLogger(__name__)

        # Token bucket state
        self._max_tokens = float(profile.calls_per_minute + profile.burst_size)
        self._tokens = self._max_tokens
        self._refill_rate = profile.calls_per_minute / 60.0  # tokens per second
        self._last_refill = time.monotonic()

        # Inter-call tracking
        self._last_call = 0.0

        # 429 back-off state
        self._backoff_until = 0.0
        self._current_backoff = 0.0

        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def acquire(self) -> float:
        """Block until an API call is permitted.

        Returns the total number of seconds spent waiting (useful for
        latency instrumentation).
        """
        total_waited = 0.0
        while True:
            wait = self._calculate_wait()
            if wait <= 0:
                return total_waited
            time.sleep(wait)
            total_waited += wait

    def report_429(self):
        """Signal that the last call received a 429 (rate-limited) response.

        Triggers exponential back-off starting at 1 s and capped at
        ``max_backoff_seconds``.
        """
        with self._lock:
            if self._current_backoff == 0:
                self._current_backoff = 1.0
            else:
                self._current_backoff = min(
                    self._current_backoff * self._profile.backoff_factor,
                    self._profile.max_backoff_seconds,
                )
            self._backoff_until = time.monotonic() + self._current_backoff
            self._tokens = 0.0
            self._logger.warning(
                "Rate limit 429: backing off %.1fs", self._current_backoff
            )

    def report_success(self):
        """Signal that the last call succeeded.  Resets back-off counter."""
        with self._lock:
            self._current_backoff = 0.0

    @property
    def profile(self) -> ThrottleProfile:
        return self._profile

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _calculate_wait(self) -> float:
        """Return seconds to wait, or 0.0 if a call is allowed now.

        When returning 0.0 a token is consumed atomically under the lock.
        """
        with self._lock:
            now = time.monotonic()

            # 1. 429 back-off takes priority
            if now < self._backoff_until:
                return self._backoff_until - now

            # 2. Enforce minimum inter-call gap
            if self._profile.min_delay_seconds > 0:
                since_last = now - self._last_call
                if since_last < self._profile.min_delay_seconds:
                    return self._profile.min_delay_seconds - since_last

            # 3. Refill tokens based on elapsed time
            elapsed = now - self._last_refill
            self._tokens = min(
                self._max_tokens,
                self._tokens + elapsed * self._refill_rate,
            )
            self._last_refill = now

            # 4. Try to consume a token
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                self._last_call = now
                return 0.0

            # 5. Not enough tokens — calculate wait for next one
            if self._refill_rate > 0:
                return (1.0 - self._tokens) / self._refill_rate
            return 1.0  # safety fallback for zero-rate edge case
