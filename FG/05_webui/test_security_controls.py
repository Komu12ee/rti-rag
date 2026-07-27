from services.security_controls import SlidingWindowRateLimiter


def test_sliding_window_limiter_blocks_and_recovers():
    now = [100.0]
    limiter = SlidingWindowRateLimiter(clock=lambda: now[0])

    assert limiter.check("login:127.0.0.1", limit=2, window_seconds=60).allowed
    assert limiter.check("login:127.0.0.1", limit=2, window_seconds=60).allowed

    blocked = limiter.check("login:127.0.0.1", limit=2, window_seconds=60)
    assert not blocked.allowed
    assert blocked.retry_after_seconds == 60

    now[0] = 161.0
    assert limiter.check("login:127.0.0.1", limit=2, window_seconds=60).allowed
