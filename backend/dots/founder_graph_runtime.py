"""Explicit runtime composition for persistent Founder Graph services."""

from __future__ import annotations

from dataclasses import dataclass
import os
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


def resolve_graph_backend() -> str:
    """Resolve one storage backend for all local composition roots.

    An explicit ``DOTS_GRAPH_BACKEND`` wins.  When it is absent, configured
    Neo4j credentials make Neo4j the normal local runtime; without credentials
    the isolated in-memory path remains available for tests.
    """

    configured = os.environ.get("DOTS_GRAPH_BACKEND")
    if configured is not None and configured.strip():
        backend = configured.strip().lower()
        if backend not in {"memory", "neo4j"}:
            raise ValueError("DOTS_GRAPH_BACKEND must be memory or neo4j")
        return backend
    return "neo4j" if os.environ.get("DOTS_NEO4J_PASSWORD", "").strip() else "memory"


def create_neo4j_driver_from_env() -> Any:
    """Create the local driver from explicit environment settings.

    ``DOTS_GRAPH_BACKEND=neo4j`` explicitly selects Neo4j.  The configured
    local password also selects Neo4j when the backend variable is absent.
    No fallback to an in-memory store is performed when the persistent
    configuration is incomplete, because silently losing writes would be
    worse than stopping.
    """

    uri = os.environ.get("DOTS_NEO4J_URI", "bolt://127.0.0.1:7687").strip()
    username = os.environ.get("DOTS_NEO4J_USERNAME", "neo4j").strip()
    password = os.environ.get("DOTS_NEO4J_PASSWORD", "")
    if not uri or not username or not password:
        raise RuntimeError(
            "DOTS_GRAPH_BACKEND=neo4j requires DOTS_NEO4J_PASSWORD; "
            "DOTS_NEO4J_URI and DOTS_NEO4J_USERNAME may also be set"
        )
    try:
        from neo4j import GraphDatabase
    except ImportError as error:  # pragma: no cover - dependency is project-required
        raise RuntimeError("the Neo4j Python driver is not installed") from error
    return GraphDatabase.driver(uri, auth=(username, password))


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
__all__ = [
    "Neo4jGraphComposition",
    "create_neo4j_driver_from_env",
    "create_neo4j_graph_composition",
    "resolve_graph_backend",
]
