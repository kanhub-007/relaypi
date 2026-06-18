"""Polling helpers for async concurrency tests.

Classical-school: these are just utilities, not test doubles themselves.
"""

import asyncio

import pytest


async def wait_until(predicate, timeout: float = 1.0, step: float = 0.005) -> None:
    """Poll ``predicate`` until it is truthy, failing after ``timeout`` seconds.

    Args:
        predicate: A zero-arg callable returning a truthy/falsy value.
        timeout: Maximum time to wait in seconds.
        step: Polling interval in seconds.
    """
    elapsed = 0.0
    while not predicate():
        if elapsed >= timeout:
            pytest.fail(f"condition not met within {timeout}s")
        await asyncio.sleep(step)
        elapsed += step
