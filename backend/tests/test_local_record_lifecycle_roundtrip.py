from __future__ import annotations

from dataclasses import fields, is_dataclass, replace
from datetime import datetime
from enum import Enum
import json
from collections.abc import Mapping

import pytest

from nebula.founder_graph import Asset, AssetKind, EgressPolicy, Idea, NodeType, RelationType, Status
from nebula.founder_graph_read import GraphReadNotFoundError, GraphReadService
from nebula.founder_graph_write import InMemoryGraphWriteService
from nebula.idea_brief import IdeaBriefSection, IdeaBriefVersion
from nebula.local_home import read_local_home
from test_founder_graph_relation_assertion_write import _setup


def _json_value(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return {field.name: _json_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


class _MemoryHomeProjectionStore:
    """Adapt the real memory write snapshot to local_home's storage boundary."""

    def __init__(self, writes: InMemoryGraphWriteService, reads: GraphReadService) -> None:
        self._writes = writes
        self._reads = reads

    def read_home(self, owner_id: str):
        snapshot = self._writes.read_snapshot()
        rows = []
        for node in snapshot.nodes:
            node_type = getattr(node, "node_type", None)
            kind = node_type.value if hasattr(node_type, "value") else node_type
            if node.owner_id != owner_id or kind not in {"idea", "asset", "owner_profile"}:
                continue
            payload = _json_value(node)
            payload["node_type"] = kind
            rows.append({
                "id": node.id,
                "owner_id": node.owner_id,
                "node_type": kind,
                "status": (
                    node_status.value if hasattr(node_status := getattr(node, "status", None), "value")
                    else node_status
                ),
                "payload_json": json.dumps(payload, ensure_ascii=False),
            })
        return tuple(rows)

    def read_briefs(self, owner_id: str):
        snapshot = self._writes.read_snapshot()
        return tuple({
            "id": brief.id,
            "owner_id": brief.owner_id,
            "root_id": brief.idea_lineage_root_id,
            "revision": brief.revision,
            "supersedes_id": brief.supersedes_id,
            "payload_json": json.dumps(_json_value(brief), ensure_ascii=False),
        } for brief in snapshot.idea_briefs if brief.owner_id == owner_id)

    def read_citations(self, owner_id: str, evidence_ids):
        snapshot = self._writes.read_snapshot()
        current_ideas = [
            node for node in snapshot.nodes
            if isinstance(node, Idea) and node.owner_id == owner_id
            and node.status in {Status.ACTIVE, Status.DRAFT}
            and not any(
                isinstance(candidate, Idea) and candidate.owner_id == owner_id
                and candidate.supersedes_id == node.id
                for candidate in snapshot.nodes
            )
        ]
        if not current_ideas:
            return {}
        try:
            projection = self._reads.fetch_idea_brief(current_ideas[0].id, owner_id=owner_id)
        except GraphReadNotFoundError:
            return {}
        return {
            citation["evidence_id"]: {"url": citation["url"], "title": citation["title"]}
            for section in projection["sections"]
            for citation in section["citations"]
            if citation["evidence_id"] in evidence_ids
        }


def _seed_shareable_graph():
    writes, idea, _claim, _evidence, brief, assertion = _setup()
    source = writes.get_node("source-relation")
    revision = writes.get_node("source-revision-relation")
    writes._nodes[source.id] = replace(source, egress_policy=EgressPolicy.SHAREABLE)
    writes._nodes[revision.id] = replace(revision, egress_policy=EgressPolicy.SHAREABLE)
    shareable_brief = brief.revise(egress_policy="shareable")
    writes.save_idea_brief(
        shareable_brief, expected_latest_revision=1, idempotency_key="save-shareable-brief",
    )
    assertion = replace(assertion, based_on_brief_id=shareable_brief.id)
    writes.save_relation_assertion(
        assertion, expected_family_revision=None, idempotency_key="save-shareable-relation",
    )
    return writes, idea, shareable_brief, assertion, GraphReadService(writes)


def test_archive_hides_idea_brief_and_semantic_relation_from_memory_reads_and_home():
    writes, idea, _brief, assertion, reads = _seed_shareable_graph()
    home_store = _MemoryHomeProjectionStore(writes, reads)
    archived = writes.archive_idea(
        idea.id, expected_revision=idea.revision, idempotency_key="archive-roundtrip",
    )

    assert all(
        hit.node.id != idea.id
        for hit in reads.search("Synthetic target", owner_id=writes.owner_id).hits
    )
    with pytest.raises(GraphReadNotFoundError):
        reads.fetch_idea_brief(idea.id, owner_id=writes.owner_id)
    with pytest.raises(GraphReadNotFoundError):
        reads.fetch_relation_assertion(assertion.id, owner_id=writes.owner_id)
    assert read_local_home(home_store, owner_id=writes.owner_id)["ideas"] == []
    assert writes.get_node(archived.target_id).status is Status.ARCHIVED


def test_restore_reprojects_eight_brief_sections_citations_and_semantic_relation():
    writes, idea, brief, assertion, reads = _seed_shareable_graph()
    home_store = _MemoryHomeProjectionStore(writes, reads)
    archived = writes.archive_idea(
        idea.id, expected_revision=idea.revision, idempotency_key="archive-before-restore",
    )
    restored = writes.restore_idea(
        archived.target_id, expected_revision=archived.revision, idempotency_key="restore-roundtrip",
    )
    current = writes.get_node(restored.target_id)

    projection = reads.fetch_idea_brief(current.id, owner_id=writes.owner_id)
    assert projection["brief_id"] == brief.id
    assert projection["idea_id"] == current.id
    assert len(projection["sections"]) == 8
    assert [section["index"] for section in projection["sections"]] == list(range(8))
    expected_citation = {
        "url": "https://example.test/source",
        "title": "Synthetic source",
        "source_id": "source-relation",
        "evidence_id": assertion.evidence_ids[0],
    }
    assert len(projection["brief_citations"]) == 8
    assert all(citations == [expected_citation] for citations in projection["brief_citations"])

    relation = reads.fetch_relation_assertion(assertion.id, owner_id=writes.owner_id)
    assert relation.source_id == current.id
    assert relation.target_id == assertion.target_id
    assert relation.based_on_brief_id == brief.id
    assert relation.based_on_brief_section_index == 1

    home = read_local_home(home_store, owner_id=writes.owner_id)
    assert [item["id"] for item in home["ideas"]] == [current.id]
    assert len(home["ideas"][0]["brief_sections"]) == 8
    expected_home_citation = {
        "url": "https://example.test/source", "title": "Synthetic source",
    }
    assert len(home["ideas"][0]["brief_citations"]) == 8
    assert all(citations == [expected_home_citation] for citations in home["ideas"][0]["brief_citations"])


def test_normal_idea_revision_does_not_revive_old_brief_and_owner_policy_stays_closed():
    writes, idea, _brief, _assertion, reads = _seed_shareable_graph()
    archived = writes.archive_idea(
        idea.id, expected_revision=idea.revision, idempotency_key="archive-before-edit",
    )
    restored = writes.restore_idea(
        archived.target_id, expected_revision=archived.revision, idempotency_key="restore-before-edit",
    )
    current = writes.get_node(restored.target_id)
    revised = current.revise(title="A normal content revision")
    writes.record_correction(
        current.id, revised, expected_revision=current.revision, idempotency_key="edit-after-restore",
    )

    with pytest.raises(GraphReadNotFoundError):
        reads.fetch_idea_brief(revised.id, owner_id=writes.owner_id)
    with pytest.raises(GraphReadNotFoundError):
        reads.fetch_idea_brief(restored.target_id, owner_id="another-owner")

    private_idea = Idea(
        owner_id=writes.owner_id, id="private-idea", title="Private idea",
        status=Status.ACTIVE, egress_policy=EgressPolicy.LOCAL_ONLY,
    )
    writes.put_node(private_idea, idempotency_key="create-private-idea")
    private_brief = IdeaBriefVersion(
        owner_id=writes.owner_id, idea_lineage_root_id=private_idea.id,
        based_on_idea_id=private_idea.id, egress_policy="shareable",
        sections=tuple(IdeaBriefSection(index=i, content=f"Private check {i}") for i in range(8)),
    )
    writes.save_idea_brief(
        private_brief, expected_latest_revision=None, idempotency_key="save-private-brief",
    )
    with pytest.raises(GraphReadNotFoundError):
        reads.fetch_idea_brief(private_idea.id, owner_id=writes.owner_id)
    assert private_idea.id in {
        item["id"] for item in read_local_home(
            _MemoryHomeProjectionStore(writes, reads), owner_id=writes.owner_id,
        )["ideas"]
    }


def test_asset_archive_restore_updates_home_and_graph_without_losing_current_idea_brief():
    writes, idea, brief, assertion, reads = _seed_shareable_graph()
    home_store = _MemoryHomeProjectionStore(writes, reads)
    asset = Asset(
        owner_id=writes.owner_id, id="reversible-asset", name="Shareable capability",
        kind=AssetKind.KNOWLEDGE, description="Public synthetic capability",
        egress_policy=EgressPolicy.SHAREABLE,
    )
    writes.put_node(asset, idempotency_key="create-reversible-asset", operation="capture_asset")
    asset_relation = replace(
        assertion, id="asset-reuse-relation", assertion_family_id="asset-reuse-family",
        target_id=asset.id, target_kind=NodeType.ASSET, predicate=RelationType.REUSES,
    )
    writes.save_relation_assertion(
        asset_relation, expected_family_revision=None, idempotency_key="create-asset-reuse",
    )

    assert reads.fetch_idea_brief(idea.id, owner_id=writes.owner_id)["brief_id"] == brief.id
    assert reads.fetch(asset.id, owner_id=writes.owner_id).id == asset.id
    assert reads.fetch_relation_assertion(asset_relation.id, owner_id=writes.owner_id).target_id == asset.id
    archived = writes.archive_asset(
        asset.id, expected_revision=asset.revision, idempotency_key="archive-reversible-asset",
    )
    with pytest.raises(GraphReadNotFoundError):
        reads.fetch(asset.id, owner_id=writes.owner_id)
    with pytest.raises(GraphReadNotFoundError):
        reads.fetch_relation_assertion(asset_relation.id, owner_id=writes.owner_id)
    assert all(item["id"] != asset.id for item in read_local_home(home_store, owner_id=writes.owner_id)["assets"])
    assert reads.fetch_idea_brief(idea.id, owner_id=writes.owner_id)["brief_id"] == brief.id

    restored = writes.restore_asset(
        archived.target_id, expected_revision=archived.revision, idempotency_key="restore-reversible-asset",
    )
    current_asset = writes.get_node(restored.target_id)
    assert reads.fetch(current_asset.id, owner_id=writes.owner_id).id == current_asset.id
    restored_relation = reads.fetch_relation_assertion(asset_relation.id, owner_id=writes.owner_id)
    assert restored_relation.source_id == idea.id
    assert restored_relation.target_id == current_asset.id
    with pytest.raises(GraphReadNotFoundError):
        reads.fetch(asset.id, owner_id=writes.owner_id)
    assert [item["id"] for item in read_local_home(home_store, owner_id=writes.owner_id)["assets"]] == [current_asset.id]
    assert reads.fetch_idea_brief(idea.id, owner_id=writes.owner_id)["brief_id"] == brief.id
