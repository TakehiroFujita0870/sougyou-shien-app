from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import json

import pytest

from dots.founder_graph import (
    Claim,
    ContentChunk,
    EgressPolicy,
    Evidence,
    Idea,
    NodeType,
    Organization,
    PersonAsset,
    RelationAssertion,
    RelationAssertionEdgeType,
    RelationType,
    RelationshipStatus,
    Status,
    SourceRevision,
    relation_assertion_structural_edges,
)
from dots.founder_graph_neo4j import Neo4jGraphGateway, _node_properties
from dots.founder_graph_neo4j_write import Neo4jGraphWriteService
from dots.founder_graph_write import GraphWriteError, IdempotencyConflictError, RevisionConflictError
from dots.idea_brief import IdeaBriefSection, IdeaBriefVersion
from dots.founder_graph_neo4j_idea_brief import _serialize_persisted_idea_brief


class Result:
    def __init__(self, rows=()):
        self.rows = tuple(rows)

    def single(self, **_kwargs):
        return self.rows[0] if self.rows else None

    def __iter__(self):
        return iter(self.rows)


class RelationTx:
    """Small transaction fake with Neo4j-like scalar properties and rollback."""

    def __init__(self, owner_id: str, nodes=(), briefs=()):
        self.owner_id = owner_id
        self.nodes = {node.id: _node_properties(node) for node in nodes}
        self.audits = {}
        self.edges = []
        for node in nodes:
            if isinstance(node, Evidence) and node.content_chunk_id is None:
                revision = SourceRevision(owner_id=node.owner_id, id=f"{node.id}-revision",
                                          source_id=f"{node.id}-source", content="Synthetic evidence source")
                chunk = ContentChunk(owner_id=node.owner_id, id=f"{node.id}-chunk",
                                     source_revision_id=revision.id, ordinal=0, char_start=0,
                                     char_end=len(revision.content), text=revision.content)
                grounded = replace(node, material_id=None, source_revision_id=revision.id,
                                   content_chunk_id=chunk.id, char_start=0, char_end=len(revision.content),
                                   locator=f"chars:0-{len(revision.content)}", content_hash=chunk.text_hash)
                self.nodes[node.id] = _node_properties(grounded)
                self.nodes[revision.id] = _node_properties(revision)
                self.nodes[chunk.id] = _node_properties(chunk)
                self.edges.extend(((revision.id, "HAS_CHUNK", chunk.id), (node.id, "EVIDENCE_FROM", chunk.id)))
        self.locks = set()
        self.fail_after_audit = False
        self.fail_after_commit = False
        self.briefs = {brief.id: self._brief_record(brief) for brief in briefs}

    def run(self, query, **params):
        owner = params.get("owner_id")
        if "MATCH (a:FounderGraphAudit" in query:
            row = self.audits.get(params["idempotency_key"])
            return Result((row,) if row and row["owner_id"] == owner else ())
        if "MATCH (i:Idea" in query and "payload_json" in query:
            if "{id: $id" in query:
                row = self.nodes.get(params["id"])
                return Result((self._node_record(row),) if row and row["owner_id"] == owner else ())
            return Result(self._node_record(row) for row in self.nodes.values()
                          if row["owner_id"] == owner and row["node_type"] == NodeType.IDEA.value)
        if "idea_lineage_root_id: $root_id" in query:
            return Result(row for row in self.briefs.values()
                          if row["owner_id"] == owner and row["idea_lineage_root_id"] == params["root_id"])
        if "_dots_idea_write_lock" in query:
            row = self.nodes.get(params["id"])
            return Result(({key: row[key] for key in ("id", "owner_id", "node_type", "revision")},)
                          if row and row["owner_id"] == owner else ())
        if "MERGE (l:FounderGraphAssertionFamilyLock" in query:
            self.locks.add((owner, params["family_key"]))
            return Result(({"family_key": params["family_key"]},))
        if "RETURN n.status AS status" in query and "MATCH (n {id: $id})" in query:
            row = self.nodes.get(params["id"])
            return Result((self._node_record(row),) if row else ())
        if "MATCH (n {id: $id})" in query and "RETURN n.owner_id" in query:
            row = self.nodes.get(params["id"])
            return Result(({"owner_id": row["owner_id"], "node_type": row["node_type"], "revision": row["revision"]},) if row else ())
        if "MATCH (n {id: $id}) RETURN n.id AS id" in query:
            row = self.nodes.get(params["id"])
            return Result((self._node_record(row),) if row else ())
        if "MATCH (n {id: $node_id, owner_id: $owner_id})" in query:
            row = self.nodes.get(params["node_id"])
            return Result((self._node_record(row),) if row and row["owner_id"] == owner else ())
        if "MATCH (n {id: $id, owner_id: $owner_id})" in query and "payload_json" in query:
            row = self.nodes.get(params["id"])
            return Result((self._node_record(row),) if row and row["owner_id"] == owner else ())
        if "MATCH (n {owner_id: $owner_id, supersedes_id:" in query:
            parent_id = params.get("parent_id", params.get("node_id"))
            return Result({"id": row["id"]} for row in self.nodes.values()
                          if row["owner_id"] == owner and row.get("supersedes_id") == parent_id)
        if "MATCH (n:RelationAssertion {owner_id: $owner_id, assertion_family_id:" in query:
            return Result(self._node_record(row) for row in self.nodes.values()
                          if row["owner_id"] == owner and row["node_type"] == NodeType.RELATION_ASSERTION.value
                          and row.get("assertion_family_id") == params["family_key"])
        if "SET n += $properties" in query and "MATCH (n:RelationAssertion" in query:
            row = self.nodes[params["id"]]
            row.update(params["properties"])
            return Result(({"id": row["id"]},))
        if "MATCH (n:RelationAssertion {id: $id, owner_id: $owner_id})" in query:
            row = self.nodes.get(params["id"])
            return Result((self._node_record(row),) if row and row["owner_id"] == owner else ())
        if "MATCH (n:RelationAssertion" in query and "supersedes_id" in query:
            return Result({"id": row["id"]} for row in self.nodes.values()
                          if row["owner_id"] == owner and row["node_type"] == NodeType.RELATION_ASSERTION.value
                          and row.get("supersedes_id") == params.get("predecessor_id"))
        if "e.content_chunk_id AS content_chunk_id" in query:
            row = self.nodes.get(params["evidence_id"])
            evidence_edge_count = sum(edge[0] == params["evidence_id"] and edge[1] == "EVIDENCE_FROM" for edge in self.edges)
            chunk_id = row.get("content_chunk_id") if row else None
            chunk = self.nodes.get(chunk_id) if chunk_id else None
            revision_id = row.get("source_revision_id") if row else None
            revision = self.nodes.get(revision_id) if revision_id else None
            expected_evidence_edge_count = sum(
                edge[0] == params["evidence_id"] and edge[1] == "EVIDENCE_FROM" and edge[2] == chunk_id
                and chunk is not None and chunk.get("owner_id") == owner
                and chunk.get("node_type") == NodeType.CONTENT_CHUNK.value
                for edge in self.edges
            )
            expected_chunk_edge_count = sum(
                edge[1] == "HAS_CHUNK" and edge[2] == chunk_id and edge[0] == revision_id
                and revision is not None and revision.get("owner_id") == owner
                and revision.get("node_type") == NodeType.SOURCE_REVISION.value
                for edge in self.edges
            )
            return Result(({
                "content_chunk_id": chunk_id, "source_revision_id": revision_id,
                "chunk_id": chunk.get("id") if chunk else None, "chunk_type": chunk.get("node_type") if chunk else None,
                "chunk_status": chunk.get("status") if chunk else None,
                "revision_id": revision.get("id") if revision else None, "revision_type": revision.get("node_type") if revision else None,
                "revision_status": revision.get("status") if revision else None,
                "evidence_edge_count": evidence_edge_count, "expected_evidence_edge_count": expected_evidence_edge_count,
                "chunk_edge_count": sum(edge[1] == "HAS_CHUNK" and edge[2] == chunk_id for edge in self.edges),
                "expected_chunk_edge_count": expected_chunk_edge_count,
            },))
        if "MATCH (e:Evidence" in query:
            row = self.nodes.get(params["id"])
            return Result(({"owner_id": row["owner_id"], "node_type": row["node_type"], "status": row["status"],
                            "egress_policy": row.get("egress_policy")},)
                          if row and row["node_type"] == NodeType.EVIDENCE.value else ())
        if "CREATE (n:RelationAssertion)" in query:
            row = dict(params["properties"])
            self.nodes[row["id"]] = row
            return Result(({"id": row["id"]},))
        if "CREATE (a)-[r:" in query:
            source = params["source_id"]
            target = params["target_id"]
            if params["assertion_id"] not in self.nodes or source not in self.nodes or target not in self.nodes:
                return Result()
            self.edges.append((params["assertion_id"], params["edge_type"], target))
            return Result(({"id": params["assertion_id"]},))
        if "CREATE (a:FounderGraphAudit" in query:
            row = {
                "owner_id": owner, "operation": params["operation"], "target_id": params["target_id"],
                "target_type": params["target_type"], "revision": params["revision"],
                "payload_fingerprint": params["payload_fingerprint"], "idempotency_key": params["idempotency_key"],
            }
            self.audits[params["idempotency_key"]] = row
            return Result((row,))
        return Result()

    def snapshot(self):
        return deepcopy((self.nodes, self.audits, self.edges, self.locks, self.briefs))

    @staticmethod
    def _node_record(row):
        if row is None:
            return None
        return {key: row.get(key) for key in ("id", "owner_id", "node_type", "revision", "status", "egress_policy", "payload_json", "assertion_family_id", "supersedes_id")}

    @staticmethod
    def _brief_record(brief):
        payload = _serialize_persisted_idea_brief(brief)
        return {
            "id": brief.id, "owner_id": brief.owner_id, "node_type": "idea_brief_version",
            "revision": brief.revision, "idea_lineage_root_id": brief.idea_lineage_root_id,
            "supersedes_id": brief.supersedes_id,
            "payload_json": payload["payload_json"],
        }


class RelationSession(RelationTx):
    def __init__(self, state):
        self.__dict__ = state.__dict__
        self.state = state

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def close(self):
        return None

    def execute_write(self, callback):
        before = self.state.snapshot()
        commit_unknown = False
        try:
            result = callback(self)
            if self.state.fail_after_commit:
                self.state.fail_after_commit = False
                commit_unknown = True
                raise RuntimeError("synthetic lost commit acknowledgement")
            if self.state.fail_after_audit:
                self.state.fail_after_audit = False
                raise RuntimeError("synthetic transaction fault")
            return result
        except Exception:
            if not commit_unknown:
                self.state.nodes, self.state.audits, self.state.edges, self.state.locks, self.state.briefs = before
            raise


class RelationDriver:
    def __init__(self, state):
        self.state = state

    def session(self, *, database):
        assert database == "neo4j"
        return RelationSession(self.state)


def fixture():
    owner = "owner-rel-neo"
    claim_a = Claim(owner_id=owner, id="claim-a", text="A")
    claim_b = Claim(owner_id=owner, id="claim-b", text="B")
    evidence = Evidence(owner_id=owner, id="evidence-rel", material_id="material-rel", claim_id=claim_a.id)
    assertion = RelationAssertion(
        owner_id=owner, id="assertion-1", source_id=claim_a.id, source_kind=NodeType.CLAIM,
        target_id=claim_b.id, target_kind=NodeType.CLAIM, predicate=RelationType.DERIVED_FROM,
        assertion_family_id="family-1", status=RelationshipStatus.CONFIRMED, evidence_ids=(evidence.id,),
    )
    state = RelationTx(owner, (claim_a, claim_b, evidence))
    gateway = Neo4jGraphGateway(RelationDriver(state), owner)
    return state, gateway, assertion


def test_persistent_assertion_writes_node_canonical_edges_audit_and_receipt_only_replay():
    state, gateway, assertion = fixture()
    writer = Neo4jGraphWriteService(gateway)

    receipt = writer.save_relation_assertion(assertion, expected_family_revision=None, idempotency_key="assertion-key")

    assert (receipt.target_id, receipt.target_type, receipt.revision, receipt.replayed) == (
        assertion.id, NodeType.RELATION_ASSERTION.value, 1, False,
    )
    persisted = state.nodes[assertion.id]
    assert persisted["assertion_family_id"] == assertion.assertion_family_id
    assert persisted.get("supersedes_id") is None
    assert tuple(state.edges[-3:]) == relation_assertion_structural_edges(assertion)
    assert state.audits["assertion-key"]["operation"] == "save_relation_assertion"
    assert state.audits["assertion-key"]["target_id"] == assertion.id
    assert writer.get_node(assertion.id) == assertion
    before = state.snapshot()

    persisted_assertion = writer.get_node(assertion.id)
    state.nodes[assertion.source_id]["status"] = Status.ARCHIVED.value
    state.edges.remove((assertion.id, RelationAssertionEdgeType.ASSERTS_TO.value, assertion.target_id))
    changed_state = state.snapshot()
    replay = writer.save_relation_assertion(
        replace(persisted_assertion, valid_from=persisted_assertion.valid_from + timedelta(seconds=1)),
        expected_family_revision=None, idempotency_key="assertion-key",
    )

    assert replay.replayed is True
    assert changed_state != before
    assert state.snapshot() == changed_state


def test_persistent_idea_assertion_calls_authoritative_brief_and_research_gate():
    owner = "owner-idea-rel"
    idea = Idea(owner_id=owner, id="idea-proof", title="synthetic")
    claim = Claim(owner_id=owner, id="claim-proof", text="supported")
    evidence = Evidence(owner_id=owner, id="evidence-proof", material_id="material-proof", claim_id=claim.id)
    brief = IdeaBriefVersion(
        owner_id=owner, id="brief-proof", idea_lineage_root_id=idea.id, based_on_idea_id=idea.id,
        research_run_ids=("synthetic-run",),
        sections=tuple(IdeaBriefSection(index=i, content="Synthetic section", evidence_ids=(evidence.id,)) for i in range(8)),
    )
    assertion = RelationAssertion(
        owner_id=owner, id="assertion-proof", source_id=idea.id, source_kind=NodeType.IDEA,
        target_id=claim.id, target_kind=NodeType.CLAIM, predicate=RelationType.ADDRESSES,
        assertion_family_id="family-proof", evidence_ids=(evidence.id,), based_on_brief_id=brief.id,
        based_on_brief_section_index=2, egress_policy=EgressPolicy.SHAREABLE,
    )
    idea = replace(idea, egress_policy=EgressPolicy.SHAREABLE)
    claim = replace(claim, egress_policy=EgressPolicy.SHAREABLE)
    evidence = replace(evidence, egress_policy=EgressPolicy.SHAREABLE)
    state = RelationTx(owner, (idea, claim, evidence), (brief,))
    gateway = Neo4jGraphGateway(RelationDriver(state), owner)
    history_calls = []
    gateway._validate_brief_run_history_tx = lambda _tx, validated_brief, validated_idea: history_calls.append(
        (validated_brief.id, validated_idea.id)
    )

    receipt = gateway.save_relation_assertion(assertion, expected_family_revision=None, idempotency_key="idea-proof-key")

    assert receipt.target_id == assertion.id
    assert history_calls == [(brief.id, idea.id)]
    assert tuple(state.edges[-3:]) == relation_assertion_structural_edges(assertion)


@pytest.mark.parametrize("person_policy", [EgressPolicy.LOCAL_ONLY, EgressPolicy.SHAREABLE])
def test_shareable_person_assertion_requires_shareable_endpoint(person_policy):
    owner = "owner-private-person"
    person = PersonAsset(owner_id=owner, id="person-private", name="Synthetic person",
                         egress_policy=person_policy)
    organization = Organization(owner_id=owner, id="org-shareable", name="Synthetic org",
                                egress_policy=EgressPolicy.SHAREABLE)
    evidence = Evidence(owner_id=owner, id="evidence-person", material_id="material-person",
                        claim_id="synthetic-claim", egress_policy=EgressPolicy.SHAREABLE)
    assertion = RelationAssertion(
        owner_id=owner, id="assertion-person", source_id=person.id, source_kind=NodeType.PERSON,
        target_id=organization.id, target_kind=NodeType.ORGANIZATION, predicate=RelationType.WORKS_AT,
        assertion_family_id="family-person", evidence_ids=(evidence.id,), egress_policy=EgressPolicy.SHAREABLE,
    )
    state = RelationTx(owner, (person, organization, evidence))
    gateway = Neo4jGraphGateway(RelationDriver(state), owner)
    before = state.snapshot()

    if person_policy is EgressPolicy.LOCAL_ONLY:
        with pytest.raises(GraphWriteError, match="shareable relation assertion requires shareable endpoints"):
            gateway.save_relation_assertion(assertion, expected_family_revision=None, idempotency_key="private-person")
        assert state.snapshot() == before
    else:
        receipt = gateway.save_relation_assertion(
            assertion, expected_family_revision=None, idempotency_key="shareable-person",
        )
        assert receipt.target_id == assertion.id
        assert tuple(state.edges[-3:]) == relation_assertion_structural_edges(assertion)


def test_persistent_assertion_revision_cas_and_idempotency_conflicts_are_write_free():
    state, gateway, assertion = fixture()
    writer = Neo4jGraphWriteService(gateway)
    before = state.snapshot()
    with pytest.raises(RevisionConflictError):
        writer.save_relation_assertion(assertion, expected_family_revision=1, idempotency_key="stale")
    assert state.snapshot() == before

    writer.save_relation_assertion(assertion, expected_family_revision=None, idempotency_key="key")
    before = state.snapshot()
    with pytest.raises(IdempotencyConflictError):
        writer.save_relation_assertion(replace(assertion, status=RelationshipStatus.PROPOSED), expected_family_revision=None, idempotency_key="key")
    assert state.snapshot() == before


@pytest.mark.parametrize("case", ["foreign_endpoint", "wrong_endpoint_type", "inactive_endpoint", "superseded_endpoint", "foreign_evidence", "inactive_evidence", "missing_evidence_lineage", "missing_chunk_lineage", "evidence_to_wrong_label", "evidence_to_foreign_owner", "wrong_label_into_chunk", "foreign_owner_into_chunk"])
def test_persistent_assertion_rejects_invalid_owner_type_or_status_without_partial_write(case):
    state, gateway, assertion = fixture()
    if case == "foreign_endpoint":
        state.nodes[assertion.source_id]["owner_id"] = "foreign-owner"
    elif case == "wrong_endpoint_type":
        state.nodes[assertion.source_id]["node_type"] = NodeType.IDEA.value
    elif case == "inactive_endpoint":
        state.nodes[assertion.source_id]["status"] = Status.ARCHIVED.value
    elif case == "superseded_endpoint":
        successor = Claim(owner_id=assertion.owner_id, id="claim-successor", text="revised",
                          supersedes_id=assertion.source_id, revision=2)
        state.nodes[successor.id] = _node_properties(successor)
    elif case == "foreign_evidence":
        state.nodes[assertion.evidence_ids[0]]["owner_id"] = "foreign-owner"
    elif case == "missing_evidence_lineage":
        evidence = state.nodes[assertion.evidence_ids[0]]
        state.edges.remove((assertion.evidence_ids[0], "EVIDENCE_FROM", evidence["content_chunk_id"]))
    elif case == "missing_chunk_lineage":
        evidence = state.nodes[assertion.evidence_ids[0]]
        state.edges.remove((evidence["source_revision_id"], "HAS_CHUNK", evidence["content_chunk_id"]))
    elif case == "evidence_to_wrong_label":
        target = Claim(owner_id=assertion.owner_id, id="extra-claim-target", text="Synthetic")
        state.nodes[target.id] = _node_properties(target)
        state.edges.append((assertion.evidence_ids[0], "EVIDENCE_FROM", target.id))
    elif case == "evidence_to_foreign_owner":
        target = Claim(owner_id="foreign-owner", id="extra-foreign-target", text="Synthetic")
        state.nodes[target.id] = _node_properties(target)
        state.edges.append((assertion.evidence_ids[0], "EVIDENCE_FROM", target.id))
    elif case == "wrong_label_into_chunk":
        origin = Claim(owner_id=assertion.owner_id, id="extra-claim-origin", text="Synthetic")
        state.nodes[origin.id] = _node_properties(origin)
        chunk_id = state.nodes[assertion.evidence_ids[0]]["content_chunk_id"]
        state.edges.append((origin.id, "HAS_CHUNK", chunk_id))
    elif case == "foreign_owner_into_chunk":
        origin = SourceRevision(owner_id="foreign-owner", id="extra-foreign-origin",
                                source_id="foreign-source", content="Synthetic")
        state.nodes[origin.id] = _node_properties(origin)
        chunk_id = state.nodes[assertion.evidence_ids[0]]["content_chunk_id"]
        state.edges.append((origin.id, "HAS_CHUNK", chunk_id))
    else:
        state.nodes[assertion.evidence_ids[0]]["status"] = Status.RETRACTED.value
    before = state.snapshot()

    with pytest.raises(GraphWriteError):
        gateway.save_relation_assertion(assertion, expected_family_revision=None, idempotency_key=f"invalid-{case}")

    assert state.snapshot() == before


@pytest.mark.parametrize("private_node", ["endpoint", "evidence"])
def test_shareable_assertion_rejects_private_endpoint_or_evidence_without_writes(private_node):
    state, gateway, assertion = fixture()
    assertion = replace(assertion, egress_policy=EgressPolicy.SHAREABLE)
    for node_id in (assertion.source_id, assertion.target_id, *assertion.evidence_ids):
        state.nodes[node_id]["egress_policy"] = EgressPolicy.SHAREABLE.value
    if private_node == "endpoint":
        state.nodes[assertion.source_id]["egress_policy"] = EgressPolicy.LOCAL_ONLY.value
    else:
        state.nodes[assertion.evidence_ids[0]]["egress_policy"] = EgressPolicy.LOCAL_ONLY.value
    before = state.snapshot()

    with pytest.raises(GraphWriteError, match="shareable relation assertion"):
        gateway.save_relation_assertion(
            assertion, expected_family_revision=None, idempotency_key=f"private-{private_node}",
        )

    assert state.snapshot() == before


def test_persistent_assertion_same_family_successor_updates_predecessor_atomically():
    state, gateway, assertion = fixture()
    first = gateway.save_relation_assertion(assertion, expected_family_revision=None, idempotency_key="first")
    successor = replace(assertion, id="assertion-2", revision=2, supersedes_id=assertion.id)

    receipt = gateway.save_relation_assertion(successor, expected_family_revision=1, idempotency_key="second")

    assert first.target_id == assertion.id and receipt.target_id == successor.id
    assert state.nodes[assertion.id]["status"] == RelationshipStatus.SUPERSEDED.value
    assert json.loads(state.nodes[assertion.id]["payload_json"])["status"] == RelationshipStatus.SUPERSEDED.value
    assert tuple(state.edges[-4:]) == relation_assertion_structural_edges(successor)
    assert state.audits["second"]["revision"] == 2


def test_changed_target_successor_starts_new_family_and_keeps_structural_supersedes_edge():
    state, gateway, assertion = fixture()
    gateway.save_relation_assertion(assertion, expected_family_revision=None, idempotency_key="old")
    replacement_claim = Claim(owner_id=assertion.owner_id, id="claim-c", text="C")
    state.nodes[replacement_claim.id] = _node_properties(replacement_claim)
    successor = replace(
        assertion, id="assertion-target-change", target_id=replacement_claim.id,
        assertion_family_id="family-target-change", revision=1, supersedes_id=assertion.id,
    )

    receipt = gateway.save_relation_assertion(successor, expected_family_revision=None, idempotency_key="new-family")

    assert receipt.target_id == successor.id
    assert state.edges[-1] == (successor.id, RelationAssertionEdgeType.SUPERSEDES.value, assertion.id)
    assert state.nodes[assertion.id]["status"] == RelationshipStatus.SUPERSEDED.value


@pytest.mark.parametrize("case", ["missing_latest_brief", "evidence_outside_section"])
def test_persistent_idea_assertion_rejects_invalid_brief_proof_without_writes(case):
    owner = "owner-idea-invalid"
    idea = Idea(owner_id=owner, id="idea-invalid", title="synthetic")
    claim = Claim(owner_id=owner, id="claim-invalid", text="supported")
    evidence = Evidence(owner_id=owner, id="evidence-invalid", material_id="material-invalid", claim_id=claim.id)
    brief = IdeaBriefVersion(
        owner_id=owner, id="brief-invalid", idea_lineage_root_id=idea.id, based_on_idea_id=idea.id,
        research_run_ids=("synthetic-run",),
        sections=tuple(IdeaBriefSection(index=i, content="Synthetic section", evidence_ids=(evidence.id,) if i != 2 else ()) for i in range(8)),
    )
    assertion = RelationAssertion(
        owner_id=owner, id="assertion-invalid", source_id=idea.id, source_kind=NodeType.IDEA,
        target_id=claim.id, target_kind=NodeType.CLAIM, predicate=RelationType.ADDRESSES,
        assertion_family_id="family-invalid", evidence_ids=(evidence.id,),
        based_on_brief_id="missing-brief" if case == "missing_latest_brief" else brief.id,
        based_on_brief_section_index=2,
    )
    state = RelationTx(owner, (idea, claim, evidence), (brief,))
    gateway = Neo4jGraphGateway(RelationDriver(state), owner)
    gateway._validate_brief_run_history_tx = lambda *_args: None
    before = state.snapshot()

    with pytest.raises(GraphWriteError):
        gateway.save_relation_assertion(assertion, expected_family_revision=None, idempotency_key=f"invalid-{case}")

    assert state.snapshot() == before


@pytest.mark.parametrize("case", ["top_level", "provenance"])
def test_typed_get_node_rejects_malformed_persisted_assertion_payload(case):
    state, gateway, assertion = fixture()
    writer = Neo4jGraphWriteService(gateway)
    gateway.save_relation_assertion(assertion, expected_family_revision=None, idempotency_key="stored")
    if case == "top_level":
        state.nodes[assertion.id]["payload_json"] = "{}"
    else:
        payload = json.loads(state.nodes[assertion.id]["payload_json"])
        del payload["provenance"]["idempotency_key"]
        state.nodes[assertion.id]["payload_json"] = json.dumps(payload)

    with pytest.raises(GraphWriteError):
        writer.get_node(assertion.id)


def test_persistent_assertion_late_failure_rolls_back_node_edges_and_audit():
    state, gateway, assertion = fixture()
    before = state.snapshot()
    state.fail_after_audit = True

    with pytest.raises(Exception):
        gateway.save_relation_assertion(assertion, expected_family_revision=None, idempotency_key="fault")

    assert state.snapshot() == before


def test_unknown_commit_recovers_only_the_exact_persisted_receipt():
    state, gateway, assertion = fixture()
    state.fail_after_commit = True

    receipt = gateway.save_relation_assertion(assertion, expected_family_revision=None, idempotency_key="unknown-commit")

    assert receipt.replayed is True
    assert state.audits["unknown-commit"]["target_id"] == assertion.id
    assert tuple(state.edges[-3:]) == relation_assertion_structural_edges(assertion)


def test_relation_family_scalar_properties_are_added_to_node_projection():
    _, _, assertion = fixture()
    properties = _node_properties(assertion)
    assert properties["assertion_family_id"] == assertion.assertion_family_id
    assert properties.get("supersedes_id") is None
