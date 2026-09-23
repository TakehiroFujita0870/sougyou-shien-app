from datetime import datetime, timezone

import pytest

from dots.founder_graph import (
    ContentChunk,
    DomainValidationError,
    EntityRevision,
    EgressPolicy,
    Facet,
    NodeType,
    RelationAssertion,
    RelationType,
    RelationshipStatus,
    project_shareable,
)


UTC = timezone.utc


def test_entity_revision_keeps_stable_entity_id_and_freezes_public_payload() -> None:
    revision = EntityRevision(
        owner_id="owner-1",
        entity_id="idea-1",
        entity_type=NodeType.IDEA,
        revision=1,
        payload_schema="idea.v2",
        public_payload={"title": "Founder Graph", "tags": ["founder"]},
    )

    assert revision.node_type is NodeType.ENTITY_REVISION
    assert revision.entity_id == "idea-1"
    assert revision.id != revision.entity_id
    assert revision.content_hash is not None
    assert revision.public_payload["tags"] == ("founder",)
    with pytest.raises(TypeError):
        revision.public_payload["title"] = "changed"  # type: ignore[index]


def test_entity_revision_rejects_self_anchor_and_hash_mismatch() -> None:
    with pytest.raises(DomainValidationError, match="entity_id must differ"):
        EntityRevision(
            owner_id="owner-1",
            id="idea-1",
            entity_id="idea-1",
            entity_type=NodeType.IDEA,
            revision=1,
            payload_schema="idea.v2",
            public_payload={"title": "Founder Graph"},
        )

    with pytest.raises(DomainValidationError, match="content_hash must match"):
        EntityRevision(
            owner_id="owner-1",
            entity_id="idea-1",
            entity_type=NodeType.IDEA,
            revision=1,
            payload_schema="idea.v2",
            public_payload={"title": "Founder Graph"},
            content_hash="0" * 64,
        )


def test_relation_assertion_requires_evidence_for_inferred_and_confirmed() -> None:
    common = dict(
        owner_id="owner-1",
        source_id="person-1",
        source_kind=NodeType.PERSON,
        target_id="idea-1",
        target_kind=NodeType.IDEA,
        predicate=RelationType.CAN_CONTRIBUTE_TO,
        assertion_family_id="family-1",
        confidence=0.8,
        valid_from=datetime(2026, 9, 23, tzinfo=UTC),
        expires_at=datetime(2026, 10, 23, tzinfo=UTC),
    )

    with pytest.raises(DomainValidationError, match="require evidence"):
        RelationAssertion(status=RelationshipStatus.INFERRED, **common)

    inferred = RelationAssertion(
        status=RelationshipStatus.INFERRED,
        evidence_ids=("evidence-1",),
        **common,
    )
    assert inferred.node_type is NodeType.RELATION_ASSERTION
    assert inferred.predicate is RelationType.CAN_CONTRIBUTE_TO

    with pytest.raises(DomainValidationError, match="network relations must be proposed or inferred"):
        RelationAssertion(
            status=RelationshipStatus.CONFIRMED,
            evidence_ids=("evidence-1",),
            **common,
        )


def test_content_chunk_validates_range_and_does_not_share_local_text() -> None:
    chunk = ContentChunk(
        owner_id="owner-1",
        source_revision_id="source-revision-1",
        ordinal=0,
        char_start=10,
        char_end=22,
        text="A bounded excerpt",
        egress_policy=EgressPolicy.SHAREABLE,
    )

    projection = project_shareable(chunk)
    assert chunk.node_type is NodeType.CONTENT_CHUNK
    assert projection["text_hash"] == chunk.text_hash
    assert "text" not in projection
    assert "content_locator" not in projection

    with pytest.raises(DomainValidationError, match="char_end must be greater"):
        ContentChunk(
            owner_id="owner-1",
            source_revision_id="source-revision-1",
            ordinal=0,
            char_start=22,
            char_end=22,
            text="A bounded excerpt",
        )


def test_facet_normalizes_values_and_relation_predicate_allowlist_is_explicit() -> None:
    facet = Facet(owner_id="owner-1", namespace="business-model", value="  SaaS  ")

    assert facet.node_type is NodeType.FACET
    assert facet.normalized_value == "saas"
    assert RelationType.CLASSIFIED_AS.value == "CLASSIFIED_AS"
    assert RelationType.MERGED_INTO.value == "MERGED_INTO"
