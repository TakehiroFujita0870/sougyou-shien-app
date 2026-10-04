"""Small on-demand driver scope shared by local dashboard adapters."""
from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Callable, Iterator
from typing import Any


@contextmanager
def managed_neo4j_driver(driver_factory: Callable[[], Any]) -> Iterator[Any]:
    """Create one driver for an operation and always close it afterward."""
    driver = driver_factory()
    try:
        yield driver
    finally:
        driver.close()
