"""Conftest for pytest configuration and fixtures."""

import os

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip all live Wallapop tests unless explicitly enabled."""
    if os.getenv("RUN_LIVE_WALLAPOP_TESTS") == "1":
        return

    live_skip = pytest.mark.skip(reason="Set RUN_LIVE_WALLAPOP_TESTS=1 to run live Wallapop tests")
    for item in items:
        if item.get_closest_marker("live") is not None:
            item.add_marker(live_skip)
