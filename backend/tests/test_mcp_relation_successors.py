import pytest

from dots.founder_graph import (
    Claim,
    EgressPolicy,
    Evidence,
    MaterialKind,
    NodeType,
    Organization,
    PersonAsset,
    Provenance,
    RelationAssertion,
    RelationType,
    RelationshipStatus,
    Source,
    SourceRevision,
)
from dots.founder_graph_mcp_write import McpWriteError, McpWriteSurface
from dots.founder_graph_write import InMemoryGraphWriteService


def _seed_evidence(writes: InMemoryGraphWriteService, key: str) -> Evidence:
    surface = McpWriteSurface(writes)
    claim = Claim(owner_id="owner-1", id=f"claim-{key}", text="grounding")
    writes.put_node(claim, idempotency_key=f"seed-{claim.id}")
    captured = surface.call("capture_source", {
        "url": "https://example.test/source", "title": "Public source", "summary": "Short public summary",
        "idempotency_key": f"source-{key}",
    }, owner_id="owner-1")
    chunk_id = captured.content_chunk_ids[0]
    receipt = writes.capture_evidence(claim.id, chunk_id, idempotency_key=f"evidence-{key}")
    return writes.get_node(receipt.target_id)


def test_link_entities_extends_exact_family_and_retries_canonically() -> None:
    writes = InMemoryGraphWriteService("owner-1")
    surface = McpWriteSurface(writes)
    people = [PersonAsset(owner_id="owner-1", id=f"person-{i}", name=f"Person {i}") for i in (1, 2)]
    for person in people:
        writes.put_node(person, idempotency_key=f"seed-{person.id}")
    evidence = _seed_evidence(writes, "relation")
    original_args = {
        "source_id": people[0].id, "target_id": people[1].id,
        "relation": RelationType.INTRODUCED_BY.value, "status": RelationshipStatus.INFERRED.value,
        "confidence": 0.7, "expires_at": "2099-01-01T00:00:00Z", "evidence_ids": [evidence.id],
        "idempotency_key": "relation-v1",
    }
    first = surface.call("link_entities", original_args, owner_id="owner-1")
    original = writes.get_node(first.target_id)
    assert isinstance(original, RelationAssertion)

    revision_args = {
        **original_args,
        "supersedes_id": original.id,
        "expected_family_revision": original.revision,
        "confidence": 0.8,
        "idempotency_key": "relation-v2",
    }
    second = surface.call("link_entities", revision_args, owner_id="owner-1")
    replay = surface.call("link_entities", revision_args, owner_id="owner-1")
    successor = writes.get_node(second.target_id)
    assert successor.assertion_family_id == original.assertion_family_id
    assert successor.revision == original.revision + 1
    assert successor.supersedes_id == original.id
    assert successor.status is RelationshipStatus.INFERRED
    assert replay.replayed and replay.target_id == successor.id
    assert writes.get_node(original.id).status is RelationshipStatus.SUPERSEDED


def test_link_entities_rejects_missing_or_stale_family_revision() -> None:
    writes = InMemoryGraphWriteService("owner-1")
    surface = McpWriteSurface(writes)
    people = [PersonAsset(owner_id="owner-1", id=f"stale-person-{i}", name=f"P{i}") for i in (1, 2)]
    for person in people:
        writes.put_node(person, idempotency_key=f"seed-{person.id}")
    evidence = _seed_evidence(writes, "stale")
    args = {
        "source_id": people[0].id, "target_id": people[1].id,
        "relation": RelationType.INTRODUCED_BY.value, "status": RelationshipStatus.INFERRED.value,
        "confidence": 0.7, "expires_at": "2099-01-01T00:00:00Z", "evidence_ids": [evidence.id],
        "idempotency_key": "stale-v1",
    }
    first = surface.call("link_entities", args, owner_id="owner-1")
    prior = writes.get_node(first.target_id)
    for bad in ({"supersedes_id": prior.id}, {"supersedes_id": prior.id, "expected_family_revision": 0}):
        with pytest.raises(McpWriteError):
            surface.call("link_entities", {**args, **bad, "idempotency_key": f"bad-{len(str(bad))}"}, owner_id="owner-1")


def test_link_entities_status_omitted_correction_replays_after_superseding_predecessor() -> None:
    writes = InMemoryGraphWriteService("owner-1")
    surface = McpWriteSurface(writes)
    people = [PersonAsset(owner_id="owner-1", id=f"implicit-status-person-{i}", name=f"P{i}") for i in (1, 2)]
    for person in people:
        writes.put_node(person, idempotency_key=f"seed-{person.id}")
    evidence = _seed_evidence(writes, "implicit-status")
    original = surface.call("link_entities", {
        "source_id": people[0].id, "target_id": people[1].id,
        "relation": RelationType.INTRODUCED_BY.value, "confidence": 0.7,
        "expires_at": "2099-01-01T00:00:00Z", "evidence_ids": [evidence.id],
        "idempotency_key": "implicit-status-v1",
    }, owner_id="owner-1")
    prior = writes.get_node(original.target_id)
    args = {
        "source_id": people[0].id, "target_id": people[1].id,
        "relation": RelationType.INTRODUCED_BY.value, "confidence": 0.7,
        "expires_at": "2099-01-01T00:00:00Z", "evidence_ids": [evidence.id],
        "supersedes_id": prior.id, "expected_family_revision": prior.revision,
        "idempotency_key": "implicit-status-v2",
    }
    first = surface.call("link_entities", args, owner_id="owner-1")
    replay = surface.call("link_entities", args, owner_id="owner-1")
    successor = writes.get_node(first.target_id)
    assert successor.status is RelationshipStatus.PROPOSED
    assert replay.replayed and replay.target_id == successor.id


def test_retract_relation_assertion_is_evidence_based_and_idempotent() -> None:
    writes = InMemoryGraphWriteService("owner-1")
    surface = McpWriteSurface(writes)
    people = [PersonAsset(owner_id="owner-1", id=f"retract-person-{i}", name=f"P{i}") for i in (1, 2)]
    for person in people:
        writes.put_node(person, idempotency_key=f"seed-{person.id}")
    evidence = _seed_evidence(writes, "retract")
    initial = surface.call("link_entities", {
        "source_id": people[0].id, "target_id": people[1].id,
        "relation": RelationType.INTRODUCED_BY.value, "status": RelationshipStatus.INFERRED.value,
        "confidence": 0.7, "expires_at": "2099-01-01T00:00:00Z", "evidence_ids": [evidence.id],
        "idempotency_key": "retract-link",
    }, owner_id="owner-1")
    prior = writes.get_node(initial.target_id)
    args = {
        "supersedes_id": prior.id, "expected_family_revision": prior.revision,
        "evidence_ids": [evidence.id], "idempotency_key": "retract-link-command",
    }
    receipt = surface.call("retract_relation_assertion", args, owner_id="owner-1")
    replay = surface.call("retract_relation_assertion", args, owner_id="owner-1")
    retracted = writes.get_node(receipt.target_id)
    assert retracted.status is RelationshipStatus.RETRACTED
    assert retracted.revision == 2 and retracted.supersedes_id == prior.id
    assert replay.replayed and replay.target_id == receipt.target_id


def test_retract_relation_assertion_schema_is_closed() -> None:
    definition = next(tool for tool in McpWriteSurface(InMemoryGraphWriteService("owner-1")).tool_definitions() if tool["name"] == "retract_relation_assertion")
    assert definition["inputSchema"]["additionalProperties"] is False
    assert definition["inputSchema"]["required"] == ["supersedes_id", "expected_family_revision", "evidence_ids", "idempotency_key"]


def _confirmed_work_relation_fixture():
    writes = InMemoryGraphWriteService("owner-1")
    surface = McpWriteSurface(writes)
    person = PersonAsset(owner_id="owner-1", id="confirmed-worker", name="Worker")
    organization = Organization(owner_id="owner-1", id="confirmed-employer", name="Employer")
    writes.put_node(person, idempotency_key="seed-confirmed-worker")
    writes.put_node(organization, idempotency_key="seed-confirmed-employer")
    evidence = _seed_evidence(writes, "confirmed-work")
    relation = RelationAssertion(
        owner_id="owner-1", id="confirmed-work-relation", source_id=person.id,
        target_id=organization.id, source_kind=NodeType.PERSON, target_kind=NodeType.ORGANIZATION,
        predicate=RelationType.WORKS_AT, assertion_family_id="confirmed-work-family",
        status=RelationshipStatus.CONFIRMED, evidence_ids=(evidence.id,),
        provenance=Provenance(actor="local-owner", operation="owner-confirmed", target_id="confirmed-work-relation"),
    )
    writes.save_relation_assertion(relation, expected_family_revision=None, idempotency_key="seed-confirmed-work")
    return writes, surface, relation, evidence


def test_confirmed_owner_relation_cannot_be_corrected_or_retracted_by_model_tools() -> None:
    writes, surface, confirmed, evidence = _confirmed_work_relation_fixture()
    base = {
        "source_id": confirmed.source_id, "target_id": confirmed.target_id,
        "relation": confirmed.predicate.value, "evidence_ids": [evidence.id],
        "supersedes_id": confirmed.id, "expected_family_revision": confirmed.revision,
    }
    for args in (
        {**base, "idempotency_key": "correct-confirmed-inherit-status"},
        {**base, "status": RelationshipStatus.INFERRED.value, "idempotency_key": "correct-confirmed-explicit-status"},
    ):
        with pytest.raises(McpWriteError, match="confirmed relation"):
            surface.call("link_entities", args, owner_id="owner-1")
    with pytest.raises(McpWriteError, match="confirmed relation"):
        surface.call("retract_relation_assertion", {
            "supersedes_id": confirmed.id, "expected_family_revision": confirmed.revision,
            "evidence_ids": [evidence.id], "idempotency_key": "retract-confirmed",
        }, owner_id="owner-1")
    assert writes.get_node(confirmed.id).status is RelationshipStatus.CONFIRMED
    assert not any(node.supersedes_id == confirmed.id for node in writes.nodes() if isinstance(node, RelationAssertion))
