import pytest

from neo4j_revision_lock_transactions import TaggedDriver, is_blocked_status


class _Transaction:
    def __init__(self):
        self.committed = self.rolled_back = False
    def commit(self):
        self.committed = True
    def rollback(self):
        self.rolled_back = True


class _Session:
    def __init__(self):
        self.transaction, self.metadata, self.closed = _Transaction(), None, False
    def __enter__(self):
        return self
    def __exit__(self, *_args):
        self.closed = True
    def close(self):
        self.closed = True
    def begin_transaction(self, *, metadata):
        self.metadata = metadata
        return self.transaction


class _Driver:
    def __init__(self):
        self.session_value, self.session_kwargs = _Session(), None
    def session(self, **kwargs):
        self.session_kwargs = kwargs
        return self.session_value


def test_transaction_metadata_uses_public_begin_transaction_and_commits():
    driver = _Driver()
    with TaggedDriver(driver, "a" * 32, "writer-a").session(database="neo4j") as session:
        assert session.execute_write(lambda _tx: "done") == "done"
    assert driver.session_kwargs == {"database": "neo4j"}
    assert driver.session_value.metadata == {
        "dots_revision_lock_run": "a" * 32,
        "dots_revision_lock_writer": "writer-a",
    }
    assert driver.session_value.transaction.committed
    assert not driver.session_value.transaction.rolled_back
    assert driver.session_value.closed


def test_tagged_session_close_delegates_to_driver_session():
    driver = _Driver()
    session = TaggedDriver(driver, "a" * 32, "writer-a").session(database="neo4j")
    session.close()
    assert driver.session_value.closed


def test_transaction_metadata_failure_rolls_back_and_preserves_original_error():
    driver = _Driver()
    with TaggedDriver(driver, "a" * 32, "writer-b").session(database="neo4j") as session:
        with pytest.raises(ValueError, match="synthetic callback failure"):
            session.execute_write(lambda _tx: (_ for _ in ()).throw(ValueError("synthetic callback failure")))
    assert driver.session_value.transaction.rolled_back
    assert not driver.session_value.transaction.committed


@pytest.mark.parametrize("status", ["Blocked", "Blocked by: [node(42)]", " Blocked by: [relationship(7)] "])
def test_blocked_status_accepts_current_and_extended_shapes(status):
    assert is_blocked_status(status)


@pytest.mark.parametrize("status", ["Running", "Closing", "Terminated", None, 1])
def test_blocked_status_rejects_nonblocked_values(status):
    assert not is_blocked_status(status)
