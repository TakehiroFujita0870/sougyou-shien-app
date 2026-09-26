"""Test-only public API wrappers for tagging revision-lock transactions."""

from __future__ import annotations

from typing import Any, Callable, Mapping


def is_blocked_status(status: Any) -> bool:
    if not isinstance(status, str):
        return False
    normalized = status.strip()
    return normalized == "Blocked" or normalized.startswith("Blocked by:")


class TaggedSession:
    def __init__(self, session: Any, metadata: Mapping[str, str]):
        self._session, self._metadata = session, dict(metadata)

    def __enter__(self):
        self._session.__enter__()
        return self

    def __exit__(self, *args: Any):
        return self._session.__exit__(*args)

    def close(self) -> None:
        close = getattr(self._session, "close", None)
        if callable(close):
            close()

    def execute_write(self, work: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        transaction = self._session.begin_transaction(metadata=self._metadata)
        try:
            result = work(transaction, *args, **kwargs)
            transaction.commit()
            return result
        except BaseException:
            transaction.rollback()
            raise


class TaggedDriver:
    def __init__(self, driver: Any, run_id: str, writer: str, purpose: str = "revision_lock"):
        self.driver, self.run_id, self.writer, self.purpose = driver, run_id, writer, purpose

    def session(self, *, database: str):
        metadata = {
            f"dots_{self.purpose}_run": self.run_id,
            f"dots_{self.purpose}_writer": self.writer,
        }
        return TaggedSession(self.driver.session(database=database), metadata)
