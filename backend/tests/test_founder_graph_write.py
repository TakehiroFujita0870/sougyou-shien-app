from __future__ import annotations

from datetime import datetime, timezone

import pytest

from dots.founder_graph import (
    EgressPolicy,
    Evidence,
    Idea,
    NodeType,
    PersonAsset,
    ResearchCampaign,
    RelationType,
    Relationship,
    Source,
    SourceRevision,
)
from dots.founder_graph_write import (
    GraphWriteError,
    IdempotencyConflictError,
    InMemoryGraphWriteService,
    NodeAlreadyExistsError,
    RevisionConflictError,
)


def _service() -> InMemoryGraphWriteService:
    return InMemoryGraphWriteService("owner-1")


def _idea(identifier: str = "idea-1", title: str = "Founder idea", owner: str = "owner-1") -> Idea:
    return Idea(owner_id=owner, id=identifier, title=title)


def _person(identifier: str = "person-1") -> PersonAsset:
    return PersonAsset(owner_id="owner-1", id=identifier, name="A founder")


def test_put_node_is_idempotent_and_audited() -> None:
    service = _service()
    node = _idea()

    first = service.put_node(node, idempotency_key="idem-1", operation="capture_idea")
    replay = service.put_node(node, idempotency_key="idem-1", operation="capture_idea")

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.target_id == node.id
    assert service.nodes() == (node,)
    assert len(service.audit_events()) == 1
    assert service.audit_events()[0].payload_fingerprint
    assert service.audit_events()[0].target_type == NodeType.IDEA.value


def test_idempotency_key_conflict_does_not_mutate_state() -> None:
    service = _service()
    service.put_node(_idea(), idempotency_key="idem-1")

    with pytest.raises(IdempotencyConflictError):
        service.put_node(_idea(title="Changed"), idempotency_key="idem-1")

    assert service.get_node("idea-1").title == "Founder idea"
    assert len(service.audit_events()) == 1


def test_owner_and_node_type_boundaries_fail_closed() -> None:
    service = _service()
    with pytest.raises(GraphWriteError, match="owner"):
        service.put_node(_idea(owner="owner-2"), idempotency_key="wrong-owner")

    class UnknownNode:
        id = "unknown-1"
        owner_id = "owner-1"
        node_type = "arbitrary"

    with pytest.raises(GraphWriteError, match="allowlist"):
        service.put_node(UnknownNode(), idempotency_key="unknown-type")

    with pytest.raises(GraphWriteError, match="allowlisted"):
        service.put_node(_idea(), idempotency_key="bad-operation", operation="delete")


def test_link_requires_existing_allowlisted_same_owner_endpoints() -> None:
    service = _service()
    person = _person()
    idea = _idea()
    evidence = Evidence(owner_id="owner-1", id="evidence-1", material_id="material-1", claim_id="claim-1")
    service.put_node(person, idempotency_key="person")
    service.put_node(idea, idempotency_key="idea")
    service.put_node(evidence, idempotency_key="evidence")
    relation = Relationship(
        owner_id="owner-1",
        source_id=person.id,
        source_kind=NodeType.PERSON,
        source_owner_id="owner-1",
        relation=RelationType.CAN_CONTRIBUTE_TO,
        target_id=idea.id,
        target_kind=NodeType.IDEA,
        target_owner_id="owner-1",
        evidence_ids=(evidence.id,),
        confidence=0.8,
        expires_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
    )

    receipt = service.link_entities(relation, idempotency_key="link-1")
    replay = service.link_entities(relation, idempotency_key="link-1")
    assert receipt.target_type == "relationship"
    assert replay.replayed is True
    assert len(service.relations()) == 1

    missing = Relationship(
        owner_id="owner-1",
        source_id=person.id,
        source_kind=NodeType.PERSON,
        source_owner_id="owner-1",
        relation=RelationType.CAN_CONTRIBUTE_TO,
        target_id="missing-idea",
        target_kind=NodeType.IDEA,
        target_owner_id="owner-1",
        evidence_ids=(evidence.id,),
        confidence=0.8,
        expires_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
    )
    with pytest.raises(GraphWriteError, match="already exist"):
        service.link_entities(missing, idempotency_key="missing-link")


def test_expected_revision_and_immutable_correction_contract() -> None:
    service = _service()
    original = _idea()
    service.put_node(original, idempotency_key="original")

    with pytest.raises(RevisionConflictError):
        service.put_node(_idea("idea-2"), idempotency_key="stale", expected_revision=2)
    with pytest.raises(NodeAlreadyExistsError):
        service.put_node(original, idempotency_key="different-key", expected_revision=0)

    corrected = original.revise(title="Corrected")
    receipt = service.record_correction(
        original.id,
        corrected,
        idempotency_key="correction-1",
        expected_revision=0,
    )
    assert receipt.target_id == corrected.id
    assert service.get_node(original.id) == original
    assert service.get_node(corrected.id) == corrected


def test_failed_link_rolls_back_relation_and_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service()
    person = _person()
    idea = _idea()
    evidence = Evidence(owner_id="owner-1", id="evidence-1", material_id="material-1", claim_id="claim-1")
    service.put_node(person, idempotency_key="person")
    service.put_node(idea, idempotency_key="idea")
    service.put_node(evidence, idempotency_key="evidence")
    relation = Relationship(
        owner_id="owner-1",
        source_id=person.id,
        source_kind=NodeType.PERSON,
        source_owner_id="owner-1",
        relation=RelationType.CAN_CONTRIBUTE_TO,
        target_id=idea.id,
        target_kind=NodeType.IDEA,
        target_owner_id="owner-1",
        evidence_ids=(evidence.id,),
        confidence=0.8,
        expires_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
    )
    before = service.audit_events()

    def fail_audit(*_args, **_kwargs):
        raise RuntimeError("audit sink unavailable")

    monkeypatch.setattr(service, "_append_audit", fail_audit)
    with pytest.raises(RuntimeError, match="audit sink"):
        service.link_entities(relation, idempotency_key="link-failure")

    assert service.relations() == ()
    assert service.audit_events() == before


def test_campaign_state_transitions_require_expected_revision_and_preserve_history() -> None:
    service = _service()
    campaign = ResearchCampaign(owner_id="owner-1", id="campaign-1", purpose="Evaluate idea")
    service.put_node(campaign, idempotency_key="campaign-create")
    approved = campaign.approve()
    receipt = service.put_node(
        approved,
        idempotency_key="campaign-approve",
        expected_revision=campaign.aggregate_revision,
    )

    assert receipt.revision == approved.aggregate_revision
    assert service.get_node(campaign.id) == approved
    assert service.node_history(campaign.id) == (campaign, approved)
    with pytest.raises(RevisionConflictError):
        service.put_node(
            approved.register_run(),
            idempotency_key="stale-transition",
            expected_revision=campaign.aggregate_revision,
        )


def test_source_revisions_and_current_pointer_are_owner_scoped_and_append_only() -> None:
    service = _service()
    source = Source(owner_id="owner-1", id="source-1", title="Market source")
    service.put_node(source, idempotency_key="source-create")

    first = SourceRevision(owner_id="owner-1", source_id=source.id, id="source-revision-1", content="first")
    service.put_node(first, idempotency_key="source-revision-1")
    current = Source(
        owner_id="owner-1",
        id=source.id,
        title=source.title,
        current_revision_id=first.id,
        revision=1,
        egress_policy=EgressPolicy.LOCAL_ONLY,
    )
    service.put_node(current, idempotency_key="source-current-1", expected_revision=0)

    second = SourceRevision(
        owner_id="owner-1",
        source_id=source.id,
        id="source-revision-2",
        revision=2,
        supersedes_id=first.id,
        content="corrected",
    )
    service.put_node(second, idempotency_key="source-revision-2")
    current_second = Source(
        owner_id="owner-1",
        id=source.id,
        title=source.title,
        current_revision_id=second.id,
        revision=2,
    )
    service.put_node(current_second, idempotency_key="source-current-2", expected_revision=1)

    assert service.node_history(source.id) == (source, current, current_second)
    assert service.node_history(first.id) == (first,)
