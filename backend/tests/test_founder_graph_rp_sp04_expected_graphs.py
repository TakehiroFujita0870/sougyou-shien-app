"""RP-SP-04 synthetic post-research graph representability spike."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

import pytest

from dots.founder_graph import (
    Asset,
    Claim,
    EgressPolicy,
    Facet,
    Idea,
    NodeType,
    Organization,
    PersonAsset,
    Provenance,
    RelationAssertion,
    RelationType,
    RelationshipStatus,
    ResearchCampaign,
    ResearchRun,
    Status,
    _ALLOWED_RELATION_ENDPOINTS,
)
from dots.founder_graph_mcp_write import McpWriteSurface
from dots.founder_graph_write import InMemoryGraphWriteService
from dots.idea_brief import IdeaBriefSection, IdeaBriefVersion
from founder_graph_post_research_fixtures import (
    EXPECTED_GRAPHS,
    ExpectedGraph,
    RelationSpec,
)


def test_five_after_research_fixtures_map_to_allowed_domain_endpoints() -> None:
    assert len(EXPECTED_GRAPHS) == 5
    assert len({fixture.fixture_id for fixture in EXPECTED_GRAPHS}) == 5
    for fixture in EXPECTED_GRAPHS:
        assert len(fixture.brief_sections) == 8
        assert fixture.distractors and fixture.no_edges
        for relation in fixture.expected_relations:
            section = fixture.brief_sections[relation.section_index]
            assert "調査根拠:" in section and "非接続候補:" in section
            assert any(distractor in section for distractor in fixture.distractors)
        for relation in (*fixture.expected_relations, *fixture.no_edges):
            source, target = NodeType(relation.source_type), NodeType(relation.target_type)
            predicate = RelationType(relation.predicate)
            assert (source, target) in _ALLOWED_RELATION_ENDPOINTS[predicate]
        assert fixture.evidence_refs
    hierarchy_endpoints = _ALLOWED_RELATION_ENDPOINTS[RelationType.CLASSIFIED_AS]
    assert (NodeType.FACET, NodeType.FACET) not in hierarchy_endpoints
    assert not hasattr(Facet, "parent_id")


def _seed_case(fixture: ExpectedGraph):
    owner_id = "rp-sp04-synthetic-owner"
    writes = InMemoryGraphWriteService(owner_id)
    surface = McpWriteSurface(writes)
    ids: dict[str, str] = {}
    for entity in fixture.entities:
        args = {"name": entity.name, "idempotency_key": f"{fixture.fixture_id}-{entity.key}"}
        if entity.node_type == "idea":
            receipt = surface.call("capture_idea", {"title": entity.name, "idempotency_key": args["idempotency_key"]}, owner_id=owner_id)
        elif entity.node_type == "asset":
            receipt = surface.call("capture_asset", {**args, "kind": "artifact"}, owner_id=owner_id)
        elif entity.node_type == "person":
            receipt = surface.call("capture_person", args, owner_id=owner_id)
        elif entity.node_type == "organization":
            receipt = surface.call("capture_organization", {**args, "egress_policy": "shareable"}, owner_id=owner_id)
        elif entity.node_type == "claim":
            receipt = surface.call("append_claim", {"text": entity.name, "confidence": 0.8, "idempotency_key": args["idempotency_key"]}, owner_id=owner_id)
        elif entity.node_type == "facet":
            facet = Facet(owner_id=owner_id, id=f"{fixture.fixture_id}-{entity.key}", namespace="service_domain", value=entity.name)
            receipt = writes.put_node(facet, idempotency_key=args["idempotency_key"])
        else:
            raise AssertionError(f"unsupported synthetic entity type: {entity.node_type}")
        ids[entity.key] = receipt.target_id

    claim_id = ids["claim"]
    evidence_ids: dict[str, str] = {}
    initial_evidence_key = fixture.initial_relation.evidence_key if fixture.initial_relation else None
    seeded_evidence_refs = tuple(
        ref for ref in fixture.evidence_refs
        if initial_evidence_key is None or ref.key == initial_evidence_key
    )
    for evidence in seeded_evidence_refs:
        source = surface.call("capture_source", {
            "url": f"https://example.invalid/{fixture.fixture_id}/{evidence.key}",
            "title": f"Synthetic {evidence.key}",
            "summary": evidence.summary,
            "idempotency_key": f"{fixture.fixture_id}-source-{evidence.key}",
        }, owner_id=owner_id)
        evidence_receipt = surface.call("capture_evidence", {
            "claim_id": ids[evidence.claim_key],
            "content_chunk_id": source.content_chunk_ids[0],
            "idempotency_key": f"{fixture.fixture_id}-evidence-{evidence.key}",
        }, owner_id=owner_id)
        evidence_ids[evidence.key] = evidence_receipt.target_id
        stored_evidence = writes.get_node(evidence_receipt.target_id)
        assert stored_evidence is not None and stored_evidence.source_revision_id is not None
        stored_revision = writes.get_node(stored_evidence.source_revision_id)
        assert stored_revision is not None and evidence.summary in stored_revision.content

    idea = writes.get_node(ids["idea"])
    assert isinstance(idea, Idea)
    now = datetime.now(timezone.utc)
    campaign = ResearchCampaign(
        owner_id=owner_id, id=f"campaign-{fixture.fixture_id}", purpose="合成fixtureの完了済み調査",
        target_idea_id=idea.id, allowed_categories=("idea.summary",), trial_budget=2,
        created_at=now - timedelta(minutes=10), expires_at=now + timedelta(hours=1),
        provenance=Provenance(actor="synthetic-test", operation="create", target_id=f"campaign-{fixture.fixture_id}", occurred_at=now - timedelta(minutes=10)),
    )
    writes.put_node(campaign, idempotency_key=f"seed-{campaign.id}")
    approved = campaign.approve(approved_at=now - timedelta(minutes=5))
    writes.put_node(approved, expected_revision=campaign.aggregate_revision, idempotency_key=f"approve-{campaign.id}")
    run = ResearchRun(
        owner_id=owner_id, id=f"run-{fixture.fixture_id}", campaign_id=campaign.id,
        authorization_snapshot_id=approved.authorization_snapshot_id,
        authorization_revision=approved.authorization_revision,
        input_snapshot={"fixture_id": fixture.fixture_id}, model_snapshot="synthetic-model",
        evidence_ids=tuple(evidence_ids.values()), status=Status.COMPLETED,
        started_at=now - timedelta(minutes=3), finished_at=now - timedelta(minutes=2),
    )
    writes.record_research_run(run, expected_campaign_revision=approved.aggregate_revision, idempotency_key=f"run-{run.id}")
    evidence_by_section: dict[int, list[str]] = {}
    for ref in seeded_evidence_refs:
        if ref.section_index is not None:
            evidence_by_section.setdefault(ref.section_index, []).append(evidence_ids[ref.key])
    brief_sections = list(fixture.brief_sections)
    if fixture.initial_relation is not None:
        brief_sections[fixture.expected_relations[0].section_index] = (
            "5. 実現可能性 — 初版調査では、この点は未確認として保留した。"
            " 訂正後に判明した内容はまだ含めない。"
        )
    brief = IdeaBriefVersion(
        owner_id=owner_id, idea_lineage_root_id=idea.id, based_on_idea_id=idea.id,
        research_run_ids=(run.id,), sections=tuple(
            IdeaBriefSection(index=index, content=section, evidence_ids=tuple(evidence_by_section.get(index, ())))
            for index, section in enumerate(brief_sections)
        ),
    )
    writes.save_idea_brief(brief, expected_latest_revision=None, idempotency_key=f"brief-{fixture.fixture_id}")
    return writes, surface, ids, evidence_ids, brief


@pytest.mark.parametrize("fixture", EXPECTED_GRAPHS, ids=lambda fixture: fixture.fixture_id)
def test_expected_graphs_are_grounded_and_replayable_in_memory(fixture: ExpectedGraph) -> None:
    writes, surface, ids, evidence_ids, brief = _seed_case(fixture)
    receipt_ids = []
    planned_relations = (fixture.initial_relation,) if fixture.initial_relation else fixture.expected_relations
    for relation in planned_relations:
        arguments = {
            "source_id": ids[relation.source_key], "target_id": ids[relation.target_key],
            "relation": relation.predicate, "status": relation.status,
            "evidence_ids": [evidence_ids[relation.evidence_key]],
            "based_on_brief_id": brief.id,
            "based_on_brief_section_index": relation.section_index,
            "idempotency_key": f"{fixture.fixture_id}-relation-{relation.key}",
        }
        if relation.confidence is not None:
            arguments["confidence"] = relation.confidence
        if relation.expires_at is not None:
            arguments["expires_at"] = relation.expires_at
        first = surface.call("link_entities", arguments, owner_id=writes.owner_id)
        replay = surface.call("link_entities", arguments, owner_id=writes.owner_id)
        assert not first.replayed
        assert replay.replayed and replay.target_id == first.target_id
        assertion = writes.get_node(first.target_id)
        assert isinstance(assertion, RelationAssertion)
        assert assertion.source_id == ids[relation.source_key]
        assert assertion.target_id == ids[relation.target_key]
        assert assertion.predicate is RelationType(relation.predicate)
        assert assertion.status is RelationshipStatus(relation.status)
        assert assertion.confidence == relation.confidence
        expected_expiry = datetime.fromisoformat(relation.expires_at.replace("Z", "+00:00")) if relation.expires_at else None
        assert assertion.expires_at == expected_expiry
        assert assertion.evidence_ids == (evidence_ids[relation.evidence_key],)
        assert assertion.based_on_brief_id == brief.id
        assert assertion.based_on_brief_section_index == relation.section_index
        receipt_ids.append(first.target_id)

    if fixture.initial_relation is not None:
        initial = writes.get_node(receipt_ids[0])
        corrected = fixture.expected_relations[0]
        assert isinstance(initial, RelationAssertion)
        campaign = writes.get_node(f"campaign-{fixture.fixture_id}")
        prior_run = writes.get_node(f"run-{fixture.fixture_id}")
        assert isinstance(campaign, ResearchCampaign) and isinstance(prior_run, ResearchRun)
        assert prior_run.evidence_ids == (evidence_ids[fixture.initial_relation.evidence_key],)
        assert fixture.expected_relations[0].evidence_key not in evidence_ids
        corrected_ref = next(ref for ref in fixture.evidence_refs if ref.key == corrected.evidence_key)
        correction_source = surface.call("capture_source", {
            "url": f"https://example.invalid/{fixture.fixture_id}/{corrected_ref.key}",
            "title": f"Synthetic {corrected_ref.key}",
            "summary": corrected_ref.summary,
            "idempotency_key": f"{fixture.fixture_id}-source-{corrected_ref.key}",
        }, owner_id=writes.owner_id)
        correction_evidence = surface.call("capture_evidence", {
            "claim_id": ids[corrected_ref.claim_key],
            "content_chunk_id": correction_source.content_chunk_ids[0],
            "idempotency_key": f"{fixture.fixture_id}-evidence-{corrected_ref.key}",
        }, owner_id=writes.owner_id)
        evidence_ids[corrected_ref.key] = correction_evidence.target_id
        corrected_node = writes.get_node(correction_evidence.target_id)
        assert corrected_node is not None and corrected_node.source_revision_id is not None
        corrected_revision = writes.get_node(corrected_node.source_revision_id)
        assert corrected_revision is not None and corrected_ref.summary in corrected_revision.content
        correction_time = datetime.now(timezone.utc)
        correction_run = replace(
            prior_run,
            id=f"run-{fixture.fixture_id}-correction",
            evidence_ids=(correction_evidence.target_id,),
            started_at=correction_time - timedelta(seconds=10),
            finished_at=correction_time - timedelta(seconds=5),
            provenance=Provenance(
                actor="synthetic-test", operation="record_correction_run",
                target_id=f"run-{fixture.fixture_id}-correction",
                occurred_at=correction_time - timedelta(seconds=10),
            ),
        )
        run_receipt = writes.record_research_run(
            correction_run, expected_campaign_revision=campaign.aggregate_revision,
            idempotency_key=f"{fixture.fixture_id}-correction-run",
        )
        assert run_receipt.target_id == correction_run.id
        assert correction_run.evidence_ids == (correction_evidence.target_id,)
        revised_section = replace(
            brief.sections[corrected.section_index],
            content=fixture.brief_sections[corrected.section_index],
            evidence_ids=(evidence_ids[corrected.evidence_key],),
        )
        revised_brief = brief.revise(
            sections=(revised_section,),
            research_run_ids=(*brief.research_run_ids, correction_run.id),
            change_reason="架空の追加調査による根拠訂正",
        )
        writes.save_idea_brief(
            revised_brief, expected_latest_revision=brief.revision,
            idempotency_key=f"{fixture.fixture_id}-corrected-brief",
        )
        assert correction_run.id in revised_brief.research_run_ids
        assert revised_brief.sections[corrected.section_index].evidence_ids == (correction_evidence.target_id,)
        assert "改訂調査では" in revised_brief.sections[corrected.section_index].content
        assert correction_evidence.target_id not in brief.sections[corrected.section_index].evidence_ids
        brief = revised_brief
        successor = replace(
            initial,
            id=f"{fixture.fixture_id}-corrected-assertion",
            revision=2,
            evidence_ids=(evidence_ids[corrected.evidence_key],),
            based_on_brief_id=brief.id,
            based_on_brief_section_index=corrected.section_index,
            supersedes_id=initial.id,
            valid_from=datetime.now(timezone.utc),
            provenance=Provenance(actor="synthetic-test", operation="correction", target_id=f"{fixture.fixture_id}-corrected-assertion"),
        )
        saved = writes.save_relation_assertion(
            successor, expected_family_revision=1, idempotency_key=f"{fixture.fixture_id}-corrected",
        )
        replay = writes.save_relation_assertion(
            successor, expected_family_revision=1, idempotency_key=f"{fixture.fixture_id}-corrected",
        )
        assert not saved.replayed and replay.replayed and replay.target_id == saved.target_id
        assert successor.source_id == ids[corrected.source_key]
        assert successor.target_id == ids[corrected.target_key]
        assert successor.predicate is RelationType(corrected.predicate)
        assert successor.status is RelationshipStatus(corrected.status)
        assert successor.confidence == corrected.confidence
        assert successor.expires_at is None
        assert successor.evidence_ids == (correction_evidence.target_id,)
        assert successor.based_on_brief_id == brief.id
        assert successor.based_on_brief_section_index == corrected.section_index
        receipt_ids.append(saved.target_id)

    assert len(receipt_ids) == len(fixture.expected_relations) + (1 if fixture.initial_relation else 0)
    assertions = tuple(node for node in writes.nodes() if isinstance(node, RelationAssertion))
    assert len(assertions) == len(fixture.expected_relations) + (1 if fixture.initial_relation else 0)
    assert all(
        not (node.source_id == ids[edge.source_key] and node.target_id == ids[edge.target_key] and node.predicate is RelationType(edge.predicate) and node.status is not RelationshipStatus.SUPERSEDED)
        for edge in fixture.no_edges for node in assertions
    )

    if fixture.initial_relation is not None:
        initial = assertions[0]
        current = next(node for node in assertions if node.status is not RelationshipStatus.SUPERSEDED)
        assert initial.status is RelationshipStatus.SUPERSEDED
        assert current.supersedes_id == initial.id
        assert current.assertion_family_id == initial.assertion_family_id
        assert current.based_on_brief_id != initial.based_on_brief_id


def test_rp_sp04_fixture_claim_evidence_alignment_is_explicit() -> None:
    fixture = next(item for item in EXPECTED_GRAPHS if item.fixture_id == "idea-addresses-claim")
    relation = fixture.expected_relations[0]
    ref = next(item for item in fixture.evidence_refs if item.key == relation.evidence_key)
    assert relation.target_key == ref.claim_key


def test_current_link_adapter_does_not_enforce_claim_evidence_identity() -> None:
    """Record the known adapter gap without changing production behavior in this spike."""
    fixture = next(item for item in EXPECTED_GRAPHS if item.fixture_id == "idea-addresses-claim")
    writes, surface, ids, evidence_ids, brief = _seed_case(fixture)
    other_claim = surface.call("append_claim", {
        "text": "Synthetic unrelated claim",
        "confidence": 0.8,
        "idempotency_key": "unrelated-evidence-claim",
    }, owner_id=writes.owner_id)
    source = surface.call("capture_source", {
        "url": "https://example.invalid/unrelated-evidence",
        "title": "Synthetic unrelated evidence",
        "summary": "架空の別主張に結び付く根拠",
        "idempotency_key": "unrelated-evidence-source",
    }, owner_id=writes.owner_id)
    evidence = surface.call("capture_evidence", {
        "claim_id": other_claim.target_id,
        "content_chunk_id": source.content_chunk_ids[0],
        "idempotency_key": "unrelated-evidence",
    }, owner_id=writes.owner_id)
    section_index = 2
    writes._idea_briefs[brief.id] = replace(
        brief,
        sections=tuple(
            replace(section, evidence_ids=(evidence.target_id,)) if section.index == section_index else section
            for section in brief.sections
        ),
    )
    edge = fixture.expected_relations[0]
    accepted = surface.call("link_entities", {
        "source_id": ids[edge.source_key], "target_id": ids[edge.target_key],
        "relation": edge.predicate, "status": edge.status,
        "evidence_ids": [evidence.target_id], "based_on_brief_id": brief.id,
        "based_on_brief_section_index": section_index,
        "idempotency_key": "claim-evidence-mismatch-gap",
    }, owner_id=writes.owner_id)
    assertion = writes.get_node(accepted.target_id)
    assert isinstance(assertion, RelationAssertion)
    assert writes.get_node(assertion.evidence_ids[0]).claim_id == other_claim.target_id
    assert assertion.target_id != other_claim.target_id
