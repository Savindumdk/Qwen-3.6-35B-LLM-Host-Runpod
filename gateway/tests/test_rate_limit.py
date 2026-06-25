"""Unit tests for the token-bucket internals (regression guards)."""

from __future__ import annotations

from app.rate_limit import _Bucket


def test_refund_is_capped_at_capacity():
    # Regression: an over-estimated request refunds tokens during reconciliation.
    # The refund must NOT push the bucket above capacity (which would let a later
    # request burst past the TPM limit).
    b = _Bucket(capacity=100, rate=1.0, tokens=100)
    b.consume_unchecked(-1000)  # refund 1000 tokens
    assert b.tokens <= 100


def test_overuse_may_go_negative():
    # Charging more than available is allowed to go negative (paid back over time).
    b = _Bucket(capacity=100, rate=1.0, tokens=10)
    b.consume_unchecked(50)
    assert b.tokens < 0


def test_try_consume_respects_balance():
    b = _Bucket(capacity=10, rate=0.0, tokens=5)
    assert b.try_consume(5) is True
    assert b.try_consume(1) is False  # bucket now empty, no refill (rate 0)
