from __future__ import annotations

from dots.founder_graph import NodeType
from dots.founder_graph_neo4j_read import required_node_id, required_owner
from dots.founder_graph_read_contract import (
    FIELD_ALLOWLIST,
    NON_CURRENT_STATUSES,
    result_rows,
    row_value,
    tokens,
)


def test_shared_read_contract_keeps_projection_allowlist_and_helper_semantics() -> None:
    assert tuple(FIELD_ALLOWLIST[NodeType.IDEA]) == (
        "title", "summary", "description", "source_text", "tags", "status",
        "egress_policy", "revision", "supersedes_id",
    )
    assert "home_category" in FIELD_ALLOWLIST[NodeType.ASSET]
    assert {"archived", "revoked", "superseded"}.issubset(NON_CURRENT_STATUSES)
    result = [{"id": "one"}, {"id": "two"}]

    assert required_owner(" owner-1 ") == "owner-1"
    assert required_node_id(" idea-1 ") == "idea-1"
    assert tokens("創業 GRAPH\nGraph") == ("創業", "graph", "graph")
    assert row_value(result[0], "missing", "fallback") == "fallback"
    assert result_rows(result) == tuple(result)
