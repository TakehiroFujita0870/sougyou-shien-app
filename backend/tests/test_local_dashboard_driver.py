import pytest

from nebula.local_dashboard_driver import managed_neo4j_driver


def test_driver_is_created_only_when_context_is_entered_and_closed_after_success():
    events = []

    class Driver:
        def close(self):
            events.append("closed")

    def create_driver():
        events.append("created")
        return Driver()

    scope = managed_neo4j_driver(create_driver)
    assert events == []
    with scope as driver:
        assert isinstance(driver, Driver)
        assert events == ["created"]
    assert events == ["created", "closed"]


def test_driver_is_closed_when_operation_raises():
    events = []

    class Driver:
        def close(self):
            events.append("closed")

    with pytest.raises(ValueError, match="query failed"):
        with managed_neo4j_driver(lambda: Driver()) as driver:
            events.append("queried")
            raise ValueError("query failed")
    assert events == ["queried", "closed"]


def test_driver_factory_error_does_not_enter_or_mask_creation_failure():
    def create_driver():
        raise RuntimeError("driver unavailable")

    with pytest.raises(RuntimeError, match="driver unavailable"):
        with managed_neo4j_driver(create_driver):
            pytest.fail("context body must not run")
