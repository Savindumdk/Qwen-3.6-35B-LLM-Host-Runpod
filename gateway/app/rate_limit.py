"""Per-API-key rate limiting.

Three independent limits are enforced per key:

* **RPM** – requests per minute (token-bucket, smooth refill).
* **TPM** – tokens per minute (token-bucket over *estimated* prompt tokens at
  admission time, reconciled with real usage when the response completes).
* **Concurrency** – simultaneous in-flight requests (semaphore).

The implementation is in-process and lock-guarded, which is the correct altitude
for a single gateway container (the recommended deployment). For a horizontally
scaled fleet, swap :class:`RateLimiter` for a Redis-backed implementation behind
the same interface — every call site only depends on :meth:`acquire`/`release`.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from .config import get_settings


@dataclass
class _Bucket:
    """A classic token bucket. ``capacity`` tokens refill at ``rate`` per second."""

    capacity: float
    rate: float
    tokens: float = field(default=0.0)
    updated: float = field(default_factory=time.monotonic)

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self.updated
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.updated = now

    def try_consume(self, amount: float) -> bool:
        self._refill()
        if self.tokens >= amount:
            self.tokens -= amount
            return True
        return False

    def consume_unchecked(self, amount: float) -> None:
        """Charge (or, for a negative ``amount``, refund) tokens during TPM
        reconciliation.

        Charging more than is available may drive the balance negative (intended:
        an over-budget request is paid back over time). A refund is capped at
        ``capacity`` so an over-estimated request can't inflate the bucket above
        its limit and let a later request burst past the TPM ceiling.
        """
        self._refill()
        self.tokens = min(self.capacity, self.tokens - amount)


@dataclass
class _KeyState:
    rpm: _Bucket
    tpm: _Bucket
    inflight: int = 0


class RateLimitError(Exception):
    """Raised when a request exceeds a configured limit."""

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.message = message
        self.retry_after = retry_after


class RateLimiter:
    """Owns the per-key buckets and concurrency semaphores."""

    def __init__(self) -> None:
        s = get_settings()
        self._rpm = s.rate_limit_rpm
        self._tpm = s.rate_limit_tpm
        self._concurrency = s.rate_limit_concurrency
        self._states: dict[str, _KeyState] = {}
        self._lock = asyncio.Lock()

    def _state_for(self, key_id: str) -> _KeyState:
        st = self._states.get(key_id)
        if st is None:
            # Start buckets full so the first request is never throttled.
            st = _KeyState(
                rpm=_Bucket(capacity=max(self._rpm, 1), rate=self._rpm / 60.0,
                            tokens=max(self._rpm, 1)),
                tpm=_Bucket(capacity=max(self._tpm, 1), rate=self._tpm / 60.0,
                            tokens=max(self._tpm, 1)),
            )
            self._states[key_id] = st
        return st

    async def acquire(self, key_id: str, est_tokens: int) -> None:
        """Admit a request or raise :class:`RateLimitError`.

        All three checks (RPM, TPM, concurrency) happen atomically under one lock
        and ``inflight`` is incremented in the same critical section, so there is
        no check-then-act race. The caller MUST invoke :meth:`release` afterwards
        (use the context manager :meth:`slot`).
        """
        async with self._lock:
            st = self._state_for(key_id)

            # Concurrency first: it's a pure counter, so rejecting here means we
            # never have to refund RPM/TPM tokens.
            if self._concurrency and st.inflight >= self._concurrency:
                raise RateLimitError("Concurrent request limit exceeded.", retry_after=1.0)

            if self._rpm and not st.rpm.try_consume(1):
                deficit = 1 - st.rpm.tokens
                raise RateLimitError(
                    "Request-per-minute limit exceeded.",
                    retry_after=round(deficit / max(st.rpm.rate, 1e-6), 1),
                )
            if self._tpm and not st.tpm.try_consume(max(est_tokens, 1)):
                deficit = max(est_tokens, 1) - st.tpm.tokens
                # Refund the RPM token we just took, since we're rejecting.
                st.rpm.tokens = min(st.rpm.capacity, st.rpm.tokens + 1)
                raise RateLimitError(
                    "Tokens-per-minute limit exceeded.",
                    retry_after=round(deficit / max(st.tpm.rate, 1e-6), 1),
                )

            st.inflight += 1

    async def release(self, key_id: str, actual_tokens: int, est_tokens: int) -> None:
        """Release the concurrency slot and reconcile TPM with real usage."""
        async with self._lock:
            st = self._states.get(key_id)
            if st is None:
                return
            st.inflight = max(0, st.inflight - 1)
            # Charge the difference between actual and estimated tokens.
            delta = actual_tokens - est_tokens
            if self._tpm and delta:
                st.tpm.consume_unchecked(delta)

    def slot(self, key_id: str, est_tokens: int) -> "_Slot":
        return _Slot(self, key_id, est_tokens)


class _Slot:
    """Async context manager pairing :meth:`acquire`/:meth:`release`."""

    def __init__(self, limiter: RateLimiter, key_id: str, est_tokens: int):
        self._limiter = limiter
        self._key_id = key_id
        self._est = est_tokens
        self.actual_tokens = est_tokens

    async def __aenter__(self) -> "_Slot":
        await self._limiter.acquire(self._key_id, self._est)
        return self

    async def __aexit__(self, *exc) -> None:
        await self._limiter.release(self._key_id, self.actual_tokens, self._est)
