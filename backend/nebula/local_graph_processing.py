"""Owner-scoped read-only summary of durable graph-processing job states."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol


JOB_STATES = ("pending", "leased", "succeeded", "failed", "superseded")


class GraphProcessingReadError(RuntimeError):
    """Raised when persisted job state cannot be safely summarized."""


class GraphProcessingStore(Protocol):
    def read_counts(self, owner_id: str) -> Mapping[str, int]: ...


class Neo4jGraphProcessingStore:
    """Aggregate state counts without returning job IDs or stored payloads."""

    _QUERY = """
MATCH (job:FounderGraphJob {owner_id: $owner_id})
RETURN
  count(CASE WHEN job.state = 'pending' THEN 1 END) AS pending,
  count(CASE WHEN job.state = 'leased' THEN 1 END) AS leased,
  count(CASE WHEN job.state = 'succeeded' THEN 1 END) AS succeeded,
  count(CASE WHEN job.state = 'failed' THEN 1 END) AS failed,
  count(CASE WHEN job.state = 'superseded' THEN 1 END) AS superseded,
  count(CASE WHEN job.state IS NULL OR NOT (job.state IN $known_states) THEN 1 END) AS unknown_state_count
"""

    def __init__(self, driver: Any, *, database: str = "neo4j") -> None:
        self._driver = driver
        self._database = database

    def read_counts(self, owner_id: str) -> dict[str, int]:
        if not isinstance(owner_id, str) or not owner_id.strip():
            raise ValueError("owner_id is required")
        with self._driver.session(database=self._database) as session:
            row = session.execute_read(lambda tx: tx.run(
                self._QUERY,
                owner_id=owner_id,
                known_states=list(JOB_STATES),
            ).single())
        if row is None:
            raise GraphProcessingReadError("job summary is missing")
        counts = {state: _count(row, state) for state in JOB_STATES}
        if _count(row, "unknown_state_count") != 0:
            raise GraphProcessingReadError("job summary contains an unsupported state")
        return counts


def _count(row: Any, name: str) -> int:
    value = row.get(name) if isinstance(row, Mapping) else row[name]
    if type(value) is not int or value < 0:
        raise GraphProcessingReadError("job summary contains an invalid count")
    return value
