"""Explicit runtime composition for persistent Founder Graph services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .founder_graph_neo4j import Neo4jGraphGateway
from .founder_graph_neo4j_read import Neo4jGraphReadService
from .founder_graph_neo4j_write import Neo4jGraphWriteService


@dataclass(frozen=True, slots=True)
class Neo4jGraphComposition:
    """The read and write ports bound to one owner and one driver."""

    gateway: Neo4jGraphGateway
    writes: Neo4jGraphWriteService
    reads: Neo4jGraphReadService


def create_neo4j_graph_composition(
    driver: Any,
    owner_id: str,
    *,
    database: str = "neo4j",
) -> Neo4jGraphComposition:
    """Build persistent graph ports without connecting or migrating implicitly."""

    gateway = Neo4jGraphGateway(driver, owner_id, database=database)
    return Neo4jGraphComposition(
        gateway=gateway,
        writes=Neo4jGraphWriteService(gateway),
        reads=Neo4jGraphReadService(gateway),
    )
__all__ = ["Neo4jGraphComposition", "create_neo4j_graph_composition"]
