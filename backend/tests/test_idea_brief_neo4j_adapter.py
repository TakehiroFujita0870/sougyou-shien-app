from __future__ import annotations

from typing import Any

from nebula import idea_brief_neo4j


class _CanonicalStore:
    def __init__(self, gateway: Any) -> None:
        self.gateway = gateway

    def get(self, brief_id: str) -> str:
        return f"get:{brief_id}"

    def get_latest(self, root_id: str) -> str:
        return f"latest:{root_id}"

    def save(self, *args: Any, **kwargs: Any) -> tuple[tuple[Any, ...], dict[str, Any]]:
        return args, kwargs


def test_runtime_adapter_delegates_to_owner_bound_canonical_store(monkeypatch) -> None:
    monkeypatch.setattr(idea_brief_neo4j, "_CanonicalIdeaBriefStore", _CanonicalStore)
    driver = object()
    store = idea_brief_neo4j.Neo4jIdeaBriefStore(
        driver, "owner-1", database="founder_graph",
    )

    assert store._store.gateway.driver is driver
    assert store._store.gateway.owner_id == "owner-1"
    assert store._store.gateway.database == "founder_graph"
    assert store.get("brief-1") == "get:brief-1"
    assert store.latest("idea-root") == "latest:idea-root"
    assert store.get_latest("idea-root") == "latest:idea-root"
