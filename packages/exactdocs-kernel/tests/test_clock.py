from datetime import UTC

from exactdocs_kernel import Clock, SystemClock


def test_system_clock_is_a_clock_and_returns_aware_utc_time() -> None:
    clock: Clock = SystemClock()

    assert clock.now().tzinfo is UTC
