"""Owner-bound compatibility adapter for canonical IdeaBrief persistence.

The gateway and write service remain the sole persistence implementation.
"""

from __future__ import annotations

from typing import Any

from .founder_graph_neo4j import Neo4jGraphGateway
from .founder_graph_neo4j_write import (
    Neo4jIdeaBriefStore as _CanonicalIdeaBriefStore,
    WriteReceipt,
)
from .idea_brief import IdeaBriefVersion


class Neo4jIdeaBriefStore:
    """Driver-based adapter exposing the local runtime's brief store contract."""

    def __init__(self, driver: Any, owner_id: str, *, database: str = "neo4j") -> None:
        gateway = Neo4jGraphGateway(driver, owner_id, database=database)
        self._store = _CanonicalIdeaBriefStore(gateway)

    @property
    def owner_id(self) -> str:
        """Return the single owner bound to the underlying canonical gateway."""
        return self._store.gateway.owner_id

    def save(
        self,
        brief: IdeaBriefVersion,
        *,
        expected_latest_revision: int | None,
        idempotency_key: str,
        actor: str = "local-owner",
    ) -> WriteReceipt:
        return self._store.save(
            brief,
            expected_latest_revision=expected_latest_revision,
            idempotency_key=idempotency_key,
            actor=actor,
        )

    def get(self, brief_id: str) -> IdeaBriefVersion | None:
        return self._store.get(brief_id)

    def latest(self, idea_lineage_root_id: str) -> IdeaBriefVersion | None:
        return self._store.get_latest(idea_lineage_root_id)

    def get_latest(self, idea_lineage_root_id: str) -> IdeaBriefVersion | None:
        return self.latest(idea_lineage_root_id)


__all__ = ["Neo4jIdeaBriefStore"]
