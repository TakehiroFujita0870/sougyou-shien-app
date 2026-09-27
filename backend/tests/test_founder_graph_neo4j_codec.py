from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import json
from types import MappingProxyType

import pytest

from dots.founder_graph import (
    Asset,
    Claim,
    ContentChunk,
    EgressPolicy,
    Evidence,
    Idea,
    NodeType,
    PersonAsset,
    RelationAssertion,
    RelationType,
    Source,
    SourceRevision,
    Status,
)
from dots.founder_graph_neo4j import (
    _content_chunk_ids as gateway_content_chunk_ids,
    _node_properties as gateway_node_properties,
    _node_revision as gateway_node_revision,
    _record_value as gateway_record_value,
    _rows as gateway_rows,
    _single as gateway_single,
)
from dots.founder_graph_neo4j_codec import (
    _content_chunk_ids,
    _json_value,
    _node_properties,
    _node_revision,
    _record_value,
    _rows,
    _single,
)
from dots.founder_graph_write import GraphWriteError


class _StrictSingleResult:
    def __init__(self, value):
        self.value = value
        self.strict_values = []

    def single(self, *, strict):
        self.strict_values.append(strict)
        return self.value


class _LegacySingleResult:
    def __init__(self, value):
        self.value = value
        self.calls = 0

    def single(self):
        self.calls += 1
        return self.value


class _SingleOnlyResult:
    def single(self):
        return {"id": "only"}

    def __iter__(self):
        raise TypeError("single row only")


class _IndexedRecord:
    def __getitem__(self, key):
        if key == "id":
            return "row-1"
        raise KeyError(key)


def test_codec_preserves_node_serialization_and_search_property_contract() -> None:
    idea = Idea(
        owner_id="owner-1", id="idea-1", title="Synthetic idea", summary="Short summary",
        source_text="private source payload", tags=("alpha", "beta"), status=Status.ACTIVE,
        egress_policy=EgressPolicy.SHAREABLE, revision=3, supersedes_id="idea-previous",
    )
    chunk = ContentChunk(
        owner_id="owner-1", id="chunk-1", source_revision_id="revision-1", ordinal=0,
        char_start=0, char_end=26, text="private chunk payload", egress_policy=EgressPolicy.LOCAL_ONLY,
    )

    assert _node_properties(idea) == gateway_node_properties(idea)
    properties = _node_properties(idea)
    assert properties["node_type"] == NodeType.IDEA.value
    assert properties["status"] == Status.ACTIVE.value
    assert properties["egress_policy"] == EgressPolicy.SHAREABLE.value
    assert properties["revision"] == 3
    assert properties["supersedes_id"] == "idea-previous"
    assert json.loads(properties["payload_json"])["source_text"] == "private source payload"

    assert _node_properties(chunk) == gateway_node_properties(chunk)
    chunk_properties = _node_properties(chunk)
    assert "private chunk payload" in chunk_properties["payload_json"]
    assert "private chunk payload" not in chunk_properties["search_text"]
    assert chunk_properties["source_revision_id"] == "revision-1"


def test_codec_preserves_typed_references_for_persisted_record_kinds() -> None:
    source = Source(
        owner_id="owner-1", id="source-1", title="Source", current_revision_id="source-revision-1",
    )
    source_revision = SourceRevision(
        owner_id="owner-1", id="source-revision-1", source_id="source-1", content="source body",
        revision=2, supersedes_id="source-revision-0",
    )
    asset = Asset(
        owner_id="owner-1", id="asset-1", name="Asset", revision=2, supersedes_id="asset-0",
    )
    person = PersonAsset(
        owner_id="owner-1", id="person-1", name="Person", revision=2, supersedes_id="person-0",
    )
    claim = Claim(
        owner_id="owner-1", id="claim-1", text="Claim", revision=1, supersedes_id="claim-0",
    )
    evidence = Evidence(
        owner_id="owner-1", id="evidence-1", claim_id="claim-1",
        source_revision_id="source-revision-1", content_chunk_id="chunk-1", char_start=0, char_end=5,
        locator="chars:0-5", content_hash="a" * 64,
    )
    relation = RelationAssertion(
        owner_id="owner-1", id="relation-1", source_id="idea-1", target_id="claim-1",
        source_kind=NodeType.IDEA, target_kind=NodeType.CLAIM, predicate=RelationType.ADDRESSES,
        assertion_family_id="family-1", supersedes_id="relation-0",
    )

    expected_references = (
        (source, {"current_revision_id": "source-revision-1"}),
        (source_revision, {"source_id": "source-1", "supersedes_id": "source-revision-0"}),
        (asset, {"supersedes_id": "asset-0"}),
        (person, {"supersedes_id": "person-0"}),
        (claim, {"supersedes_id": "claim-0"}),
        (evidence, {
            "claim_id": "claim-1", "source_revision_id": "source-revision-1", "content_chunk_id": "chunk-1",
        }),
        (relation, {"assertion_family_id": "family-1", "supersedes_id": "relation-0"}),
    )
    for node, expected in expected_references:
        properties = _node_properties(node)
        assert properties == gateway_node_properties(node)
        assert {key: properties[key] for key in expected} == expected


def test_json_value_keeps_recursive_enum_datetime_and_mapping_serialization() -> None:
    class State(Enum):
        READY = "ready"

    value = MappingProxyType({
        "state": State.READY,
        "at": datetime(2026, 9, 27, tzinfo=timezone.utc),
        "nested": (EgressPolicy.SHAREABLE, MappingProxyType({"number": 2})),
    })

    assert _json_value(value) == {
        "state": "ready",
        "at": "2026-09-27T00:00:00+00:00",
        "nested": ["shareable", {"number": 2}],
    }


def test_node_revision_and_content_chunk_ids_keep_validation_contracts() -> None:
    class Aggregate:
        aggregate_revision = 2
        revision = 9

    class InvalidRevision:
        revision = True

    assert _node_revision(Aggregate()) == gateway_node_revision(Aggregate()) == 2
    with pytest.raises(GraphWriteError, match="node revision"):
        _node_revision(InvalidRevision())
    assert _content_chunk_ids('["chunk-a", "chunk-b"]') == ("chunk-a", "chunk-b")
    assert _content_chunk_ids(None) == ()
    assert _content_chunk_ids(("chunk-a",)) == gateway_content_chunk_ids(("chunk-a",))
    with pytest.raises(GraphWriteError, match="content chunk ids"):
        _content_chunk_ids('["chunk-a", 2]')


def test_record_helpers_preserve_mapping_index_and_single_row_fallbacks() -> None:
    row = {"id": "row-1"}
    assert _record_value(row, "missing", "fallback") == gateway_record_value(row, "missing", "fallback") == "fallback"
    assert _record_value(_IndexedRecord(), "id") == "row-1"

    strict = _StrictSingleResult(row)
    assert _single(strict) == gateway_single(_StrictSingleResult(row)) == row
    assert strict.strict_values == [False]
    legacy = _LegacySingleResult(row)
    assert _single(legacy) == row
    assert legacy.calls == 1
    assert _rows(_SingleOnlyResult()) == ({"id": "only"},)
    assert _rows([row, {"id": "row-2"}]) == gateway_rows([row, {"id": "row-2"}])
