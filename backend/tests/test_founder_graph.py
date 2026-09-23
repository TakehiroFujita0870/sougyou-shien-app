from dataclasses import replace
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import MappingProxyType

import pytest

from dots.founder_graph import (
    Asset,
    AssetKind,
    CampaignAuthorizationSnapshot,
    CampaignAuthorizationRegistry,
    Claim,
    ClaimType,
    EgressPolicy,
    Evidence,
    Idea,
    KnowledgeAsset,
    MaterialKind,
    Organization,
    OwnerProfile,
    Decision,
    Experiment,
    InstructionArtifact,
    PersonAsset,
    Provenance,
    ProvenanceOrigin,
    RelationType,
    Relationship,
    RelationshipStatus,
    ReportSection,
    ReportStatus,
    ReportVersion,
    REPORT_SECTION_TITLES,
    ResearchCampaign,
    ResearchMaterial,
    ResearchRun,
    Source,
    RunStatus,
    SourceRevision,
    READ_MCP_NODE_TYPES,
    validate_source_revision_history,
    Status,
    NodeType,
    project_shareable,
    validate_campaign_idea_reference,
    validate_claim_evidence_references,
    validate_evidence_references,
    validate_report_references,
    validate_references,
    validate_run_campaign_reference,
    utc_now,
)


UTC = timezone.utc


def provenance(target_id: str = "target-1", operation: str = "capture") -> Provenance:
    return Provenance(
        actor="chatgpt",
        operation=operation,
        target_id=target_id,
        source_id="source-1",
        model_snapshot="luna-logical-key@2026-09-20",
        prompt_version="prompt-v1",
        occurred_at=datetime(2026, 9, 20, 0, 0, tzinfo=UTC),
        idempotency_key=f"{operation}-{target_id}",
    )


def test_t_fg_05_idea_revision_preserves_old_state_and_provenance() -> None:
    idea = Idea(
        owner_id="owner-1",
        id="idea-1",
        title="Local founder graph",
        source_text="Keep ideas connected to evidence.",
        provenance=provenance("idea-1"),
    )

    revised = idea.revise(
        title="Local Founder Graph",
        provenance=provenance("idea-2", operation="revise"),
    )

    assert idea.id == "idea-1"
    assert idea.title == "Local founder graph"
    assert idea.revision == 0
    assert idea.status is Status.DRAFT
    assert revised.id != idea.id
    assert revised.supersedes_id == idea.id
    assert revised.revision == 1
    assert revised.provenance.operation == "revise"


def test_t_fg_05_asset_discriminates_knowledge_and_person_without_provider_fields() -> None:
    knowledge = KnowledgeAsset(owner_id="owner-1", id="asset-k", name="Unit economics", provenance=provenance("asset-k"))
    person = PersonAsset(
        owner_id="owner-1",
        id="asset-p",
        name="Potential collaborator",
        contact={"email": "private@example.test"},
        provenance=provenance("asset-p"),
    )

    assert knowledge.kind is AssetKind.KNOWLEDGE
    assert person.kind is AssetKind.PERSON
    assert person.contact["email"] == "private@example.test"
    assert person.egress_policy is EgressPolicy.LOCAL_ONLY
    assert Asset.person(owner_id="owner-1", name="Alice").kind is AssetKind.PERSON
    assert Asset.knowledge(owner_id="owner-1", name="Pricing notes").kind is AssetKind.KNOWLEDGE


def test_t_fg_12_network_relation_requires_evidence_confidence_expiry_and_inferred_state() -> None:
    expires_at = datetime(2026, 10, 1, tzinfo=UTC)
    relation = Relationship(
        owner_id="owner-1",
        source_id="person-1",
        relation=RelationType.CAN_CONTRIBUTE_TO,
        target_id="idea-1",
        source_kind=NodeType.PERSON,
        target_kind=NodeType.IDEA,
        source_owner_id="owner-1",
        target_owner_id="owner-1",
        status=RelationshipStatus.INFERRED,
        confidence=0.8,
        evidence_ids=("evidence-1",),
        expires_at=expires_at,
        provenance=provenance("relation-1", operation="infer_relation"),
    )

    assert relation.relation is RelationType.CAN_CONTRIBUTE_TO
    assert relation.status is RelationshipStatus.INFERRED
    assert relation.confidence == 0.8

    with pytest.raises(ValueError, match="evidence"):
        Relationship(
            owner_id="owner-1",
            source_id="person-1",
            relation=RelationType.CAN_CONTRIBUTE_TO,
            target_id="idea-1",
            source_kind=NodeType.PERSON,
            target_kind=NodeType.IDEA,
            source_owner_id="owner-1",
            target_owner_id="owner-1",
            status=RelationshipStatus.INFERRED,
            confidence=0.8,
            expires_at=expires_at,
        )
    with pytest.raises(ValueError, match="proposed or inferred"):
        Relationship(
            owner_id="owner-1",
            source_id="person-1",
            relation=RelationType.CAN_CONTRIBUTE_TO,
            target_id="idea-1",
            source_kind=NodeType.PERSON,
            target_kind=NodeType.IDEA,
            source_owner_id="owner-1",
            target_owner_id="owner-1",
            status=RelationshipStatus.CONFIRMED,
            confidence=0.8,
            evidence_ids=("evidence-1",),
            expires_at=expires_at,
        )


def test_research_material_and_evidence_keep_hash_locator_and_egress_policy() -> None:
    material = ResearchMaterial(
        owner_id="owner-1",
        id="material-1",
        title="Official source",
        content="A stable source excerpt.",
        kind=MaterialKind.WEB,
        locator="https://example.test/source",
        egress_policy=EgressPolicy.SHAREABLE,
        provenance=provenance("material-1"),
    )
    evidence = Evidence(
        owner_id="owner-1",
        id="evidence-1",
        material_id=material.id,
        claim_id="claim-1",
        excerpt="A stable source excerpt.",
        locator="#p=1",
        provenance=provenance("evidence-1"),
    )

    assert len(material.content_hash) == 64
    assert material.egress_policy is EgressPolicy.SHAREABLE
    assert evidence.material_id == material.id
    assert evidence.source_id == material.id


def test_t_fg_16_campaign_defaults_to_one_trial_and_scope_change_requires_reauthorization() -> None:
    campaign = ResearchCampaign(
        owner_id="owner-1",
        id="campaign-1",
        purpose="Evaluate the founder graph",
        scope={"idea_id": "idea-1", "topics": ["market"]},
        provenance=provenance("campaign-1"),
    )
    approved = campaign.approve(
        approved_at=datetime(2026, 9, 20, tzinfo=UTC),
        provenance=provenance("campaign-1", operation="approve"),
    )
    changed = approved.change_scope({"idea_id": "idea-1", "topics": ["market", "competition"]})

    assert campaign.trial_budget == 1
    assert approved.authorized is True
    assert approved.status is Status.APPROVED
    assert changed.authorized is False
    assert changed.status is Status.PENDING_APPROVAL
    assert changed.scope != approved.scope
    assert approved.can_start_run(at=datetime(2026, 9, 20, tzinfo=UTC)) is True

    expiring = ResearchCampaign(
        owner_id="owner-1",
        purpose="Expired campaign",
        expires_at=datetime(2026, 9, 21, tzinfo=UTC),
        provenance=provenance("campaign-expiring-base", operation="create"),
    )
    expired = expiring.approve(
        approved_at=datetime(2026, 9, 20, tzinfo=UTC),
        provenance=provenance("campaign-expiring", operation="approve"),
    )
    assert expired.can_start_run(at=datetime(2026, 9, 22, tzinfo=UTC)) is False


def test_t_fg_17_research_run_is_deeply_immutable_and_transport_retry_keeps_run_identity() -> None:
    input_snapshot = {"query": "market", "filters": {"shareable": True}}
    run = ResearchRun(
        owner_id="owner-1",
        id="run-1",
        campaign_id="campaign-1",
        input_snapshot=input_snapshot,
        model_snapshot="chatgpt-deep-research@2026-09-20",
        sources=("web",),
        status=RunStatus.RUNNING,
        started_at=datetime(2026, 9, 20, tzinfo=UTC),
        provenance=provenance("run-1", operation="start_run"),
    )

    input_snapshot["query"] = "mutated outside"
    with pytest.raises(TypeError):
        run.input_snapshot["query"] = "mutated inside"  # type: ignore[index]
    with pytest.raises(TypeError):
        run.input_snapshot["filters"]["shareable"] = False  # type: ignore[index]

    retried = run.retry_transport(error="temporary timeout")
    completed = retried.complete(evidence_ids=("evidence-1",), results={"summary": "done"})

    assert isinstance(run.input_snapshot, MappingProxyType)
    assert run.id == retried.id == completed.id
    assert run.status is RunStatus.RUNNING
    assert retried.status is RunStatus.RUNNING
    assert len(retried.transport_retries) == 1
    assert completed.status is RunStatus.COMPLETED
    assert completed.evidence_ids == ("evidence-1",)
    assert run.evidence_ids == ()


def test_claim_validates_confidence_and_keeps_classification_and_evidence() -> None:
    claim = Claim(
        owner_id="owner-1",
        id="claim-1",
        text="The local graph is useful.",
        claim_type=ClaimType.AI_INFERENCE,
        confidence=0.65,
        evidence_ids=("evidence-1",),
        provenance=provenance("claim-1"),
    )

    assert claim.claim_type is ClaimType.AI_INFERENCE
    assert claim.classification is ClaimType.AI_INFERENCE
    assert claim.confidence == 0.65
    assert claim.evidence_ids == ("evidence-1",)

    with pytest.raises(ValueError, match="confidence"):
        Claim(owner_id="owner-1", text="Impossible confidence", confidence=1.1)


def test_t_fg_18_report_sections_have_exact_fixed_ids_and_titles() -> None:
    assert tuple(REPORT_SECTION_TITLES) == tuple(range(8))
    assert len(REPORT_SECTION_TITLES) == 8
    assert [ReportSection(owner_id="owner-1", id=index).title for index in range(8)] == list(REPORT_SECTION_TITLES.values())
    assert ReportSection(owner_id="owner-1", id=3, facts=("price is known",), evidence_ids=("evidence-1",)).section_id == 3


def test_time_helper_returns_timezone_aware_utc_datetime() -> None:
    now = utc_now()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


def test_owner_id_is_mandatory_for_every_persisted_domain_value() -> None:
    with pytest.raises(ValueError, match="owner_id"):
        Idea(title="owner required")
    with pytest.raises(ValueError, match="owner_id"):
        ResearchMaterial(title="owner required")
    with pytest.raises(ValueError, match="owner_id"):
        Claim(text="owner required")


def test_campaign_authorization_requires_approve_and_creates_fresh_snapshot_revision() -> None:
    campaign = ResearchCampaign(
        owner_id="owner-1",
        purpose="test",
        provenance=provenance("campaign-auth-base", operation="create"),
    )

    with pytest.raises(ValueError, match="approve"):
        ResearchCampaign(owner_id="owner-1", purpose="invalid", authorized=True)
    with pytest.raises(ValueError, match="approve"):
        ResearchCampaign(owner_id="owner-1", purpose="invalid", status=Status.APPROVED)

    approved = campaign.approve(
        approved_at=datetime(2026, 9, 20, tzinfo=UTC),
        provenance=provenance("campaign-1", operation="approve"),
    )
    changed = approved.change_scope({"topic": "new"})

    assert approved.authorization_snapshot_id
    assert changed.authorization_snapshot_id != approved.authorization_snapshot_id
    assert changed.prior_authorization_snapshot_id == approved.authorization_snapshot_id
    assert changed.authorization_revision == approved.authorization_revision + 1
    assert changed.approved_at is None
    assert changed.provenance.idempotency_key != approved.provenance.idempotency_key
    with pytest.raises(ValueError, match="already authorized"):
        approved.approve(
            approved_at=datetime(2026, 9, 20, tzinfo=UTC),
            provenance=provenance("campaign-1", operation="approve-again"),
        )


def test_terminal_research_runs_reject_retransition_and_transport_retry() -> None:
    run = ResearchRun(
        owner_id="owner-1",
        campaign_id="campaign-1",
        input_snapshot={"query": "market"},
        model_snapshot="model-1",
        status=RunStatus.RUNNING,
        started_at=datetime(2026, 9, 20, tzinfo=UTC),
    ).complete(
        evidence_ids=("evidence-1",),
        provenance=provenance("run-1", operation="complete"),
    )

    with pytest.raises(ValueError, match="terminal"):
        run.complete(provenance=provenance("run-1", operation="complete-again"))
    with pytest.raises(ValueError, match="terminal"):
        run.retry_transport(error="late retry")


def test_strict_json_freeze_rejects_arbitrary_mutable_objects() -> None:
    with pytest.raises(ValueError, match="JSON-like"):
        ResearchRun(
            owner_id="owner-1",
            campaign_id="campaign-1",
            input_snapshot={"bad": object()},
            model_snapshot="model-1",
        )
    with pytest.raises(ValueError, match="JSON-like"):
        ResearchRun(
            owner_id="owner-1",
            campaign_id="campaign-1",
            input_snapshot={"bad": {1, 2}},
            model_snapshot="model-1",
        )


def test_material_hash_and_evidence_link_are_verified() -> None:
    with pytest.raises(ValueError, match="content_hash"):
        ResearchMaterial(owner_id="owner-1", title="bad", content="actual", content_hash="0" * 64)
    with pytest.raises(ValueError, match="claim or source revision"):
        Evidence(owner_id="owner-1", material_id="material-1")


def test_person_egress_projection_excludes_private_fields_and_details() -> None:
    person = PersonAsset(
        owner_id="owner-1",
        name="Public name",
        contact={},
        private_notes="private",
        egress_policy=EgressPolicy.LOCAL_ONLY,
    )
    assert project_shareable(person) == {}
    with pytest.raises(ValueError, match="local_only"):
        PersonAsset(
            owner_id="owner-1",
            name="Leaky",
            contact={"email": "x@example.test"},
            egress_policy=EgressPolicy.SHAREABLE,
        )


def test_idea_egress_projection_keeps_source_text_local_only() -> None:
    local = Idea(owner_id="owner-1", title="Private idea", source_text="raw conversation")
    shareable = Idea(
        owner_id="owner-1",
        title="Public idea",
        summary="A safe summary",
        source_text="private raw conversation",
        egress_policy=EgressPolicy.SHAREABLE,
    )

    assert project_shareable(local) == {}
    projection = project_shareable(shareable)
    assert projection["title"] == "Public idea"
    assert "source_text" not in projection


def test_relationship_matrix_and_owner_boundary_are_enforced() -> None:
    with pytest.raises(ValueError, match="endpoint"):
        Relationship(
            owner_id="owner-1",
            source_id="idea-1",
            source_kind=NodeType.IDEA,
            source_owner_id="owner-1",
            relation=RelationType.WORKS_AT,
            target_id="asset-1",
            target_kind=NodeType.ASSET,
            target_owner_id="owner-1",
        )
    with pytest.raises(ValueError, match="same owner"):
        Relationship(
            owner_id="owner-1",
            source_id="person-1",
            source_kind=NodeType.PERSON,
            source_owner_id="owner-1",
            relation=RelationType.CAN_CONTRIBUTE_TO,
            target_id="idea-1",
            target_kind=NodeType.IDEA,
            target_owner_id="owner-2",
            status=RelationshipStatus.INFERRED,
            confidence=0.8,
            evidence_ids=("evidence-1",),
            expires_at=datetime(2026, 10, 1, tzinfo=UTC),
        )


def test_report_version_is_immutable_exactly_eight_sections_and_has_metadata_hooks() -> None:
    sections = tuple(ReportSection(owner_id="owner-1", id=index) for index in range(8))
    report = ReportVersion(
        owner_id="owner-1",
        sections=sections,
        financial_formulas={"break_even": "fixed_cost / margin"},
        decision_criteria={"stop": "if runway < 3 months"},
        change_reason="initial report",
    )

    assert len(report.sections) == 8
    assert report.sections[3].title == "収益モデル"
    assert report.financial_formulas["break_even"] == "fixed_cost / margin"
    with pytest.raises(TypeError):
        report.metadata["x"] = "mutate"  # type: ignore[index]
    with pytest.raises(ValueError, match="exactly 8"):
        ReportVersion(owner_id="owner-1", sections=sections[:-1])
    with pytest.raises(ValueError, match="section id"):
        ReportSection(owner_id="owner-1", id=True)
    with pytest.raises(ValueError, match="section id"):
        ReportSection(owner_id="owner-1", id=1.0)


def test_explicit_projection_requires_active_typed_authorization_snapshot() -> None:
    person = PersonAsset(owner_id="owner-1", name="Public name", egress_policy=EgressPolicy.EXPLICIT)
    campaign = ResearchCampaign(
        owner_id="owner-1",
        id="campaign-1",
        purpose="explicit projection",
        target_idea_id=person.id,
        allowed_categories=("person",),
        expires_at=datetime(2026, 9, 30, tzinfo=UTC),
        provenance=provenance("campaign-explicit-base", operation="create"),
    ).approve(approved_at=datetime(2026, 9, 21, tzinfo=UTC))
    snapshot = campaign.authorization_snapshot
    registry = CampaignAuthorizationRegistry.from_campaign(campaign)
    with pytest.raises(ValueError, match="current campaign"):
        project_shareable(person, authorization=snapshot)
    assert project_shareable(
        person,
        authorization=snapshot,
        campaign=campaign,
        authorization_registry=registry,
        at=datetime(2026, 9, 21, tzinfo=UTC),
    )["name"] == "Public name"
    with pytest.raises(ValueError, match="owner"):
        project_shareable(person, authorization=CampaignAuthorizationSnapshot(
            owner_id="owner-2",
            campaign_id=campaign.id,
            revision=snapshot.revision,
            allowed_field_categories=("person",),
            scope_target_ids=(person.id,),
            expires_at=snapshot.expires_at,
        ),
            campaign=campaign,
            authorization_registry=registry,
        )
    with pytest.raises(ValueError, match="expired"):
        project_shareable(
            person,
            authorization=snapshot,
            campaign=campaign,
            authorization_registry=registry,
            at=datetime(2026, 10, 1, tzinfo=UTC),
        )


def test_aggregate_reference_validators_require_existence_and_same_owner() -> None:
    idea = Idea(owner_id="owner-1", id="idea-1", title="Idea")
    campaign = ResearchCampaign(
        owner_id="owner-1",
        id="campaign-1",
        purpose="test",
        target_idea_id=idea.id,
        provenance=provenance("campaign-aggregate-base", operation="create"),
    )
    approved = campaign.approve(approved_at=datetime(2026, 9, 21, tzinfo=UTC))
    snapshot = approved.authorization_snapshot
    run = ResearchRun(
        owner_id="owner-1",
        campaign_id=approved.id,
        authorization_snapshot_id=snapshot.id,
        authorization_revision=snapshot.revision,
        input_snapshot={"q": "x"},
        model_snapshot="model-1",
    )
    material = ResearchMaterial(owner_id="owner-1", id="material-1", title="Material", content="x")
    claim = Claim(owner_id="owner-1", id="claim-1", text="Claim", evidence_ids=("evidence-1",))
    evidence = Evidence(owner_id="owner-1", id="evidence-1", material_id=material.id, claim_id=claim.id)
    registry = CampaignAuthorizationRegistry.from_campaign(approved)

    validate_campaign_idea_reference(approved, idea)
    validate_run_campaign_reference(
        run,
        approved,
        snapshot,
        authorization_registry=registry,
        at=datetime(2026, 9, 21, tzinfo=UTC),
    )
    validate_evidence_references(evidence, material=material, claim=claim)
    validate_claim_evidence_references(claim, (evidence,))

    with pytest.raises(ValueError, match="different owner"):
        validate_claim_evidence_references(claim, (Evidence(owner_id="owner-2", id="evidence-1", material_id=material.id, claim_id=claim.id),))
    with pytest.raises(ValueError, match="does not exist"):
        validate_campaign_idea_reference(approved, Idea(owner_id="owner-1", id="idea-2", title="Wrong"))


def test_final_report_requires_runs_evidence_and_non_empty_typed_sections() -> None:
    sections = tuple(ReportSection(owner_id="owner-1", id=index, claim_ids=(f"claim-{index}",)) for index in range(8))
    with pytest.raises(ValueError, match="final report"):
        ReportVersion(owner_id="owner-1", sections=sections, status=ReportStatus.FINAL)
    final_sections = tuple(
        ReportSection(
            owner_id="owner-1",
            id=index,
            claim_ids=(f"claim-{index}",),
            evidence_ids=(f"evidence-{index}",),
        )
        for index in range(8)
    )
    report = ReportVersion(
        owner_id="owner-1",
        sections=final_sections,
        status=ReportStatus.FINAL,
        run_ids=("run-1",),
        evidence_ids=("evidence-1",),
        financial_formulas={"break_even": "fixed_cost / margin"},
        decision_criteria={"stop": "if runway < 3 months"},
    )
    assert report.final is True


def test_validate_report_references_rejects_cross_owner_section_claim_and_evidence() -> None:
    claim = Claim(owner_id="owner-2", id="claim-cross-owner", text="Other owner's claim")
    evidence = Evidence(
        owner_id="owner-2",
        id="evidence-cross-owner",
        material_id="material-2",
        claim_id=claim.id,
    )
    sections = tuple(
        ReportSection(
            owner_id="owner-1",
            id=index,
            claim_ids=(claim.id,) if index == 0 else (),
            evidence_ids=(evidence.id,) if index == 0 else (),
        )
        for index in range(8)
    )
    report = ReportVersion(owner_id="owner-1", sections=sections)

    with pytest.raises(ValueError, match="owner"):
        validate_report_references(report, (), (evidence,), claims=(claim,))


def test_validate_claim_evidence_references_requires_evidence_claim_identity() -> None:
    claim = Claim(owner_id="owner-1", id="claim-identity", text="Claim", evidence_ids=("evidence-identity",))
    evidence = Evidence(
        owner_id="owner-1",
        id="evidence-identity",
        material_id="material-1",
        claim_id="different-claim",
    )

    with pytest.raises(ValueError, match="claim"):
        validate_claim_evidence_references(claim, (evidence,))


def test_final_report_requires_section_claim_and_evidence_contract() -> None:
    sections = tuple(
        ReportSection(
            owner_id="owner-1",
            id=index,
            claim_ids=(f"claim-{index}",),
        )
        for index in range(8)
    )

    draft = ReportVersion(owner_id="owner-1", sections=sections, status=ReportStatus.DRAFT)
    assert draft.final is False

    with pytest.raises(ValueError, match="claim.*evidence|evidence.*claim|final report"):
        ReportVersion(
            owner_id="owner-1",
            sections=sections,
            status=ReportStatus.FINAL,
            run_ids=("run-1",),
            evidence_ids=("evidence-1",),
            financial_formulas={"break_even": "fixed_cost / margin"},
            decision_criteria={"stop": "if runway < 3 months"},
        )


def test_final_report_requires_financial_formulas_and_decision_criteria() -> None:
    sections = tuple(
        ReportSection(
            owner_id="owner-1",
            id=index,
            claim_ids=(f"claim-{index}",),
            evidence_ids=(f"evidence-{index}",),
        )
        for index in range(8)
    )
    common = {
        "owner_id": "owner-1",
        "sections": sections,
        "status": ReportStatus.FINAL,
        "run_ids": ("run-1",),
        "evidence_ids": ("evidence-0",),
    }

    with pytest.raises(ValueError, match="financial_formulas"):
        ReportVersion(
            **common,
            financial_formulas={"not_a_required_formula": "x"},
            decision_criteria={"stop": "if runway < 3 months"},
        )
    with pytest.raises(ValueError, match="decision_criteria"):
        ReportVersion(
            **common,
            financial_formulas={"break_even": "fixed_cost / margin"},
            decision_criteria={"not_a_required_criterion": "x"},
        )

    report = ReportVersion(
        **common,
        financial_formulas={"break_even": "fixed_cost / margin"},
        decision_criteria={"stop": "if runway < 3 months"},
    )
    assert report.final is True


def test_revision_and_new_strategy_provenance_target_new_ids_and_keep_parent() -> None:
    idea = Idea(owner_id="owner-1", id="idea-1", title="Idea", provenance=provenance("idea-1"))
    revised = idea.revise(provenance=provenance("new-idea", operation="revise"))
    assert revised.provenance.target_id == revised.id
    assert revised.parent_id == idea.id

    run = ResearchRun(owner_id="owner-1", campaign_id="campaign-1", input_snapshot={}, model_snapshot="model-1")
    strategy = run.new_strategy_run(input_snapshot={"query": "different"})
    assert strategy.provenance.target_id == strategy.id
    assert strategy.parent_id == run.id


def test_generated_provenance_requires_source_model_and_prompt_or_rule() -> None:
    with pytest.raises(ValueError, match="generated provenance"):
        Provenance(origin=ProvenanceOrigin.GENERATED)
    generated = Provenance(
        origin=ProvenanceOrigin.GENERATED,
        target_id="target-1",
        source_id="source-1",
        model_snapshot="model-1",
        rule_version="rule-1",
    )
    assert generated.origin is ProvenanceOrigin.GENERATED


def test_validate_run_campaign_reference_rejects_superseded_snapshot() -> None:
    campaign = ResearchCampaign(
        owner_id="owner-1",
        id="campaign-r1",
        purpose="Validate current authorization",
        target_idea_id="idea-1",
        allowed_categories=("idea",),
        expires_at=datetime(2026, 9, 30, tzinfo=UTC),
        provenance=provenance("campaign-r1-base", operation="create"),
    )
    approved = campaign.approve(approved_at=datetime(2026, 9, 21, tzinfo=UTC))
    old_snapshot = approved.authorization_snapshot
    changed = approved.change_scope(
        {"target_ids": ["idea-1"], "topic": "changed"},
        at=datetime(2026, 9, 21, tzinfo=UTC),
    )
    current = changed.approve(approved_at=datetime(2026, 9, 21, 1, tzinfo=UTC))
    current_snapshot = current.authorization_snapshot
    registry = CampaignAuthorizationRegistry(campaigns=(approved, current))
    run = ResearchRun(
        owner_id="owner-1",
        campaign_id=current.id,
        authorization_snapshot_id=old_snapshot.id,
        authorization_revision=old_snapshot.revision,
        input_snapshot={"query": "market"},
        model_snapshot="model-1",
    )

    with pytest.raises(ValueError, match="current|superseded"):
        validate_run_campaign_reference(
            run,
            current,
            old_snapshot,
            at=datetime(2026, 9, 21, 2, tzinfo=UTC),
            authorization_registry=registry,
        )

    current_run = ResearchRun(
        owner_id="owner-1",
        campaign_id=current.id,
        authorization_snapshot_id=current_snapshot.id,
        authorization_revision=current_snapshot.revision,
        input_snapshot={"query": "market"},
        model_snapshot="model-1",
    )
    validate_run_campaign_reference(
        current_run,
        current,
        current_snapshot,
        at=datetime(2026, 9, 21, 2, tzinfo=UTC),
        authorization_registry=registry,
    )
    assert old_snapshot.id == approved.authorization_snapshot_id
    assert old_snapshot.revision == approved.authorization_revision


def test_explicit_projection_rejects_superseded_authorization_snapshot() -> None:
    person = PersonAsset(owner_id="owner-1", id="person-r1", name="Public name", egress_policy=EgressPolicy.EXPLICIT)
    campaign = ResearchCampaign(
        owner_id="owner-1",
        id="campaign-projection-r1",
        purpose="Validate explicit projection authorization",
        target_idea_id=person.id,
        allowed_categories=("person",),
        expires_at=datetime(2026, 9, 30, tzinfo=UTC),
        provenance=provenance("campaign-projection-r1-base", operation="create"),
    )
    approved = campaign.approve(approved_at=datetime(2026, 9, 21, tzinfo=UTC))
    old_snapshot = approved.authorization_snapshot
    changed = approved.change_scope(
        {"target_ids": [person.id], "topic": "changed"},
        at=datetime(2026, 9, 21, tzinfo=UTC),
    )
    current = changed.approve(approved_at=datetime(2026, 9, 21, 1, tzinfo=UTC))
    current_snapshot = current.authorization_snapshot
    registry = CampaignAuthorizationRegistry(campaigns=(approved, current))

    with pytest.raises(ValueError, match="current|superseded"):
        project_shareable(
            person,
            authorization=old_snapshot,
            campaign=current,
            at=datetime(2026, 9, 21, 2, tzinfo=UTC),
            authorization_registry=registry,
        )
    assert project_shareable(
        person,
        authorization=current_snapshot,
        campaign=current,
        at=datetime(2026, 9, 21, 2, tzinfo=UTC),
        authorization_registry=registry,
    )["name"] == "Public name"


def test_validate_run_campaign_reference_rejects_old_aggregate_and_snapshot_from_registry() -> None:
    campaign = ResearchCampaign(
        owner_id="owner-1",
        id="campaign-r1-authority",
        purpose="Validate authoritative current aggregate",
        allowed_categories=("idea",),
        expires_at=datetime(2026, 9, 30, tzinfo=UTC),
        provenance=provenance("campaign-r1-authority-base", operation="create"),
    )
    approved = campaign.approve(approved_at=datetime(2026, 9, 21, tzinfo=UTC))
    old_snapshot = approved.authorization_snapshot
    changed = approved.change_scope({"target_ids": [approved.id]}, at=datetime(2026, 9, 21, 1, tzinfo=UTC))
    current = changed.approve(approved_at=datetime(2026, 9, 21, 2, tzinfo=UTC))
    current_snapshot = current.authorization_snapshot
    registry = CampaignAuthorizationRegistry(campaigns=(approved, current))

    old_run = ResearchRun(
        owner_id="owner-1",
        campaign_id=approved.id,
        authorization_snapshot_id=old_snapshot.id,
        authorization_revision=old_snapshot.revision,
        input_snapshot={"query": "old"},
        model_snapshot="model-1",
    )
    with pytest.raises(ValueError, match="authoritative|current|superseded"):
        validate_run_campaign_reference(
            old_run,
            approved,
            old_snapshot,
            authorization_registry=registry,
            at=datetime(2026, 9, 21, 3, tzinfo=UTC),
        )

    current_run = ResearchRun(
        owner_id="owner-1",
        campaign_id=current.id,
        authorization_snapshot_id=current_snapshot.id,
        authorization_revision=current_snapshot.revision,
        input_snapshot={"query": "current"},
        model_snapshot="model-1",
    )
    validate_run_campaign_reference(
        current_run,
        current,
        current_snapshot,
        authorization_registry=registry,
        at=datetime(2026, 9, 21, 3, tzinfo=UTC),
    )

    assert approved.authorization_snapshot_id == old_snapshot.id
    assert current.authorization_snapshot_id == current_snapshot.id


def test_explicit_projection_rejects_old_aggregate_and_snapshot_from_registry() -> None:
    person = PersonAsset(owner_id="owner-1", id="person-r1-authority", name="Public name", egress_policy=EgressPolicy.EXPLICIT)
    campaign = ResearchCampaign(
        owner_id="owner-1",
        id="campaign-projection-authority",
        purpose="Validate authoritative current projection aggregate",
        target_idea_id=person.id,
        allowed_categories=("person",),
        expires_at=datetime(2026, 9, 30, tzinfo=UTC),
        provenance=provenance("campaign-projection-authority-base", operation="create"),
    )
    approved = campaign.approve(approved_at=datetime(2026, 9, 21, tzinfo=UTC))
    old_snapshot = approved.authorization_snapshot
    changed = approved.change_scope({"target_ids": [person.id]}, at=datetime(2026, 9, 21, 1, tzinfo=UTC))
    current = changed.approve(approved_at=datetime(2026, 9, 21, 2, tzinfo=UTC))
    current_snapshot = current.authorization_snapshot
    registry = CampaignAuthorizationRegistry(campaigns=(approved, current))

    with pytest.raises(ValueError, match="authoritative|current|superseded"):
        project_shareable(
            person,
            authorization=old_snapshot,
            campaign=approved,
            authorization_registry=registry,
            at=datetime(2026, 9, 21, 3, tzinfo=UTC),
        )
    assert project_shareable(
        person,
        authorization=current_snapshot,
        campaign=current,
        authorization_registry=registry,
        at=datetime(2026, 9, 21, 3, tzinfo=UTC),
    )["name"] == "Public name"


def test_authorization_boundary_requires_registry_not_caller_supplied_current_aggregate() -> None:
    person = PersonAsset(owner_id="owner-1", id="person-r1-required", name="Public name", egress_policy=EgressPolicy.EXPLICIT)
    campaign = ResearchCampaign(
        owner_id="owner-1",
        id="campaign-r1-required",
        purpose="Require authoritative registry",
        target_idea_id=person.id,
        allowed_categories=("person",),
        expires_at=datetime(2026, 9, 30, tzinfo=UTC),
        provenance=provenance("campaign-r1-required-base", operation="create"),
    ).approve(approved_at=datetime(2026, 9, 21, tzinfo=UTC))
    snapshot = campaign.authorization_snapshot
    run = ResearchRun(
        owner_id="owner-1",
        campaign_id=campaign.id,
        authorization_snapshot_id=snapshot.id,
        authorization_revision=snapshot.revision,
        input_snapshot={"query": "x"},
        model_snapshot="model-1",
    )

    with pytest.raises(ValueError, match="authoritative registry"):
        validate_run_campaign_reference(run, campaign, snapshot, at=datetime(2026, 9, 21, 1, tzinfo=UTC))
    with pytest.raises(ValueError, match="authoritative registry"):
        validate_references(run=run, campaign=campaign, authorization=snapshot)
    with pytest.raises(ValueError, match="authoritative registry"):
        project_shareable(
            person,
            authorization=snapshot,
            campaign=campaign,
            at=datetime(2026, 9, 21, 1, tzinfo=UTC),
        )


def test_fixed_transition_at_drives_generated_provenance_occurred_at() -> None:
    approval_at = datetime(2026, 9, 21, 1, tzinfo=UTC)
    scope_change_at = datetime(2026, 9, 21, 2, tzinfo=UTC)
    run_at = datetime(2026, 9, 21, 3, tzinfo=UTC)
    campaign = ResearchCampaign(
        owner_id="owner-1",
        id="campaign-r1-time",
        purpose="Deterministic transition time",
        provenance=provenance("campaign-r1-time-base", operation="create"),
    )

    approved = campaign.approve(approved_at=approval_at)
    changed = approved.change_scope({"topic": "new"}, at=scope_change_at)
    registered = approved.register_run(at=run_at)

    assert approved.provenance.occurred_at == approval_at
    assert changed.provenance.occurred_at == scope_change_at
    assert registered.provenance.occurred_at == run_at


def test_generated_provenance_rejects_target_id_that_does_not_match_aggregate() -> None:
    generated = Provenance(
        origin=ProvenanceOrigin.GENERATED,
        target_id="different-aggregate",
        source_id="source-1",
        model_snapshot="model-1",
        prompt_version="prompt-1",
    )

    with pytest.raises(ValueError, match="target_id"):
        ResearchCampaign(owner_id="owner-1", id="campaign-r1-target", purpose="Target identity", provenance=generated)
    with pytest.raises(ValueError, match="target_id"):
        ResearchRun(
            owner_id="owner-1",
            id="run-r1-target",
            campaign_id="campaign-r1-target",
            input_snapshot={},
            model_snapshot="model-1",
            provenance=generated,
        )
    with pytest.raises(ValueError, match="target_id"):
        ResearchCampaign(owner_id="owner-1", purpose="Transition target").approve(
            approved_at=datetime(2026, 9, 21, tzinfo=UTC),
            provenance=generated,
        )


def test_generated_provenance_requires_target_id() -> None:
    with pytest.raises(ValueError, match="target_id"):
        Provenance(
            origin=ProvenanceOrigin.GENERATED,
            source_id="source-1",
            model_snapshot="model-1",
            prompt_version="prompt-1",
        )


def test_relationship_state_alias_rejects_mismatch() -> None:
    with pytest.raises(ValueError, match="agree"):
        Relationship(
            owner_id="owner-1",
            source_id="person-1",
            source_kind=NodeType.PERSON,
            source_owner_id="owner-1",
            relation=RelationType.CAN_CONTRIBUTE_TO,
            target_id="idea-1",
            target_kind=NodeType.IDEA,
            target_owner_id="owner-1",
            status=RelationshipStatus.INFERRED,
            state=RelationshipStatus.PROPOSED,
            confidence=0.8,
            evidence_ids=("evidence-1",),
            expires_at=datetime(2026, 10, 1, tzinfo=UTC),
        )


def test_plan_history_value_objects_are_owner_scoped_and_typed() -> None:
    assert Organization(owner_id="owner-1", name="Org").node_type is NodeType.ORGANIZATION
    assert SourceRevision(owner_id="owner-1", source_id="source-1", content="x").node_type is NodeType.SOURCE_REVISION
    assert OwnerProfile(owner_id="owner-1").node_type is NodeType.OWNER_PROFILE
    assert Decision(owner_id="owner-1", text="Proceed").node_type is NodeType.DECISION
    assert Experiment(owner_id="owner-1", name="Pilot").node_type is NodeType.EXPERIMENT
    assert InstructionArtifact(owner_id="owner-1", path="AGENTS.md").node_type is NodeType.INSTRUCTION_ARTIFACT


def test_authorization_registry_resolves_latest_state_across_reordered_complete_history() -> None:
    base = ResearchCampaign(
        owner_id="owner-1",
        id="campaign-r1-state-history",
        purpose="State revision history",
        target_idea_id="idea-1",
        allowed_categories=("idea",),
        provenance=provenance("campaign-r1-state-history"),
    )
    approved = base.approve(approved_at=datetime(2026, 9, 20, 1, tzinfo=UTC))
    changed = approved.change_scope(
        {"target_ids": ["idea-1"], "topic": "changed"},
        at=datetime(2026, 9, 20, 2, tzinfo=UTC),
    )
    current = changed.approve(approved_at=datetime(2026, 9, 20, 3, tzinfo=UTC))
    registered = current.register_run(at=datetime(2026, 9, 20, 4, tzinfo=UTC))

    assert (base.aggregate_revision, approved.aggregate_revision, changed.aggregate_revision) == (0, 1, 2)
    assert (current.aggregate_revision, registered.aggregate_revision) == (3, 4)
    assert approved.authorization_revision == 1
    assert changed.authorization_revision == current.authorization_revision == 2
    assert registered.authorization_snapshot == current.authorization_snapshot

    registry = CampaignAuthorizationRegistry.from_campaign_history(
        (registered, changed, base, current, approved)
    )
    resolved_campaign, resolved_snapshot = registry.resolve_current(base.id)
    assert resolved_campaign == registered
    assert resolved_snapshot == current.authorization_snapshot


def test_authorization_registry_allows_exact_snapshot_replay_but_rejects_same_id_payload_conflict() -> None:
    base = ResearchCampaign(
        owner_id="owner-1",
        id="campaign-r1-snapshot-replay",
        purpose="Snapshot replay",
        allowed_categories=("idea",),
        target_idea_id="idea-1",
        provenance=provenance("campaign-r1-snapshot-replay"),
    )
    approved = base.approve(approved_at=datetime(2026, 9, 20, 1, tzinfo=UTC))
    registered = approved.register_run(at=datetime(2026, 9, 20, 2, tzinfo=UTC))
    CampaignAuthorizationRegistry.from_campaign_history((registered, approved, approved))

    changed = registered.change_scope(
        {"target_ids": ["idea-2"]},
        at=datetime(2026, 9, 20, 3, tzinfo=UTC),
    )
    conflicting = replace(
        changed.approve(approved_at=datetime(2026, 9, 20, 4, tzinfo=UTC)),
        authorization_snapshot_id=approved.authorization_snapshot_id,
        _internal_transition=True,
    )
    with pytest.raises(ValueError, match="snapshot"):
        CampaignAuthorizationRegistry.from_campaign_history((approved, conflicting))


def test_authorization_registry_rejects_distinct_payloads_at_duplicate_state_revision() -> None:
    base = ResearchCampaign(
        owner_id="owner-1",
        id="campaign-r1-state-conflict",
        purpose="Duplicate state revision",
        target_idea_id="idea-1",
        provenance=provenance("campaign-r1-state-conflict"),
    )
    approved = base.approve(approved_at=datetime(2026, 9, 20, 1, tzinfo=UTC))
    conflicting = replace(
        approved,
        authorization_snapshot_id="authorization-conflict",
        aggregate_revision=approved.aggregate_revision,
        _internal_transition=True,
    )
    with pytest.raises(ValueError, match="ambiguous|state revision"):
        CampaignAuthorizationRegistry.from_campaign_history((approved, conflicting))


def test_campaign_transitions_reject_audit_time_before_prior_approval_or_provenance() -> None:
    prior_at = datetime(2026, 9, 20, tzinfo=UTC)
    campaign = ResearchCampaign(
        owner_id="owner-1",
        id="campaign-r1-time-order",
        purpose="Transition ordering",
        provenance=provenance("campaign-r1-time-order"),
    )
    with pytest.raises(ValueError, match="prior|chronological|time"):
        campaign.approve(approved_at=datetime(2026, 9, 19, 23, tzinfo=UTC))

    approved = campaign.approve(approved_at=datetime(2026, 9, 20, 1, tzinfo=UTC))
    with pytest.raises(ValueError, match="prior|chronological|time"):
        approved.change_scope({"topic": "too early"}, at=prior_at)

    changed = approved.change_scope({"topic": "new"}, at=datetime(2026, 9, 20, 2, tzinfo=UTC))
    current = changed.approve(approved_at=datetime(2026, 9, 20, 3, tzinfo=UTC))
    with pytest.raises(ValueError, match="prior|chronological|time"):
        current.register_run(at=datetime(2026, 9, 20, 2, 30, tzinfo=UTC))


def test_relationship_rejects_generated_provenance_target_mismatch() -> None:
    generated = Provenance(
        origin=ProvenanceOrigin.GENERATED,
        target_id="wrong-target",
        source_id="source-1",
        model_snapshot="model-1",
        prompt_version="prompt-1",
    )
    with pytest.raises(ValueError, match="target_id"):
        Relationship(
            owner_id="owner-1",
            source_id="claim-1",
            relation=RelationType.DERIVED_FROM,
            target_id="claim-2",
            source_kind=NodeType.CLAIM,
            target_kind=NodeType.CLAIM,
            source_owner_id="owner-1",
            target_owner_id="owner-1",
            provenance=generated,
        )


@pytest.mark.parametrize(
    "keys",
    (
        ("authorization",),
        ("authorization_registry",),
        ("campaign", "authorization"),
        ("campaign", "authorization_registry"),
    ),
)
def test_validate_references_rejects_orphan_authorization_inputs(keys: tuple[str, ...]) -> None:
    campaign = ResearchCampaign(owner_id="owner-1", purpose="Orphan authorization", provenance=provenance("orphan"))
    approved = campaign.approve(approved_at=datetime(2026, 9, 20, 1, tzinfo=UTC))
    values: dict[str, object] = {
        "campaign": approved,
        "authorization": approved.authorization_snapshot,
        "authorization_registry": CampaignAuthorizationRegistry.from_campaign(approved),
    }
    with pytest.raises(ValueError, match="orphan|run"):
        validate_references(**{key: values[key] for key in keys})


def _source_history_fixture(*, egress_policy: EgressPolicy = EgressPolicy.SHAREABLE) -> tuple[Source, SourceRevision, SourceRevision]:
    first = SourceRevision(
        owner_id="owner-1",
        source_id="source-r3",
        id="source-r3-revision-1",
        revision=1,
        content="first source text",
        locator="https://example.test/source",
        egress_policy=egress_policy,
        provenance=provenance("source-r3-revision-1", operation="capture"),
    )
    second = SourceRevision(
        owner_id="owner-1",
        source_id="source-r3",
        id="source-r3-revision-2",
        revision=2,
        supersedes_id=first.id,
        content="corrected source text",
        locator="https://example.test/source",
        egress_policy=egress_policy,
        provenance=provenance("source-r3-revision-2", operation="correct"),
    )
    source = Source(
        owner_id="owner-1",
        id="source-r3",
        title="Founder source",
        kind=MaterialKind.WEB,
        locator="https://example.test/source",
        current_revision_id=second.id,
        egress_policy=egress_policy,
        provenance=provenance("source-r3", operation="create"),
    )
    return source, first, second


def test_source_revision_history_requires_current_source_and_monotonic_revision() -> None:
    source, first, second = _source_history_fixture()

    assert validate_source_revision_history(source, (second, first)) == second

    with pytest.raises(ValueError, match="current"):
        validate_source_revision_history(replace(source, current_revision_id="missing"), (first, second))

    gap = replace(second, revision=3, supersedes_id=first.id)
    with pytest.raises(ValueError, match="monotonic|contiguous"):
        validate_source_revision_history(replace(source, current_revision_id=gap.id), (first, gap))


def test_source_revision_supersession_preserves_prior_revision() -> None:
    source, first, second = _source_history_fixture()
    before = (first.content, first.content_hash, first.provenance)

    current = validate_source_revision_history(source, (first, second))

    assert current is second
    assert (first.content, first.content_hash, first.provenance) == before
    assert second.supersedes_id == first.id
    assert source.current_revision_id == second.id
    assert first != second


def test_source_has_an_allowlisted_revision_relation() -> None:
    source, first, _second = _source_history_fixture()

    relationship = Relationship.from_entities(
        source=source,
        relation=RelationType.HAS_REVISION,
        target=first,
        status=RelationshipStatus.CONFIRMED,
    )

    assert relationship.relation is RelationType.HAS_REVISION


def test_source_revision_history_rejects_cross_owner_orphan_revision() -> None:
    source, first, second = _source_history_fixture()

    with pytest.raises(ValueError, match="owner"):
        validate_source_revision_history(
            source,
            (first, replace(second, owner_id="owner-2")),
        )

    with pytest.raises(ValueError, match="source_id"):
        validate_source_revision_history(
            source,
            (first, replace(second, source_id="other-source")),
        )


def _shareable_node_fixture() -> tuple[object, ...]:
    source, first, second = _source_history_fixture()
    owner = OwnerProfile(owner_id="owner-1", id="owner-1", display_name="Founder", egress_policy=EgressPolicy.SHAREABLE)
    idea = Idea(owner_id="owner-1", id="idea-r3", title="Graph idea", egress_policy=EgressPolicy.SHAREABLE)
    asset = KnowledgeAsset(owner_id="owner-1", id="asset-r3", name="Graph skill", egress_policy=EgressPolicy.SHAREABLE)
    person = PersonAsset(owner_id="owner-1", id="person-r3", name="Public person", egress_policy=EgressPolicy.SHAREABLE)
    organization = Organization(owner_id="owner-1", id="organization-r3", name="Public organization", egress_policy=EgressPolicy.SHAREABLE)
    material = ResearchMaterial(owner_id="owner-1", id="material-r3", title="Legacy material", content="legacy", egress_policy=EgressPolicy.SHAREABLE)
    claim = Claim(owner_id="owner-1", id="claim-r3", text="A supported claim", egress_policy=EgressPolicy.SHAREABLE)
    evidence = Evidence(
        owner_id="owner-1",
        id="evidence-r3",
        material_id=material.id,
        claim_id=claim.id,
        source_revision_id=second.id,
        excerpt="supported",
        egress_policy=EgressPolicy.SHAREABLE,
    )
    campaign = ResearchCampaign(owner_id="owner-1", id="campaign-r3", purpose="Read campaign", egress_policy=EgressPolicy.SHAREABLE)
    run = ResearchRun(owner_id="owner-1", id="run-r3", campaign_id=campaign.id, input_snapshot={"q": "x"}, model_snapshot="model-r3", egress_policy=EgressPolicy.SHAREABLE)
    sections = tuple(ReportSection(owner_id="owner-1", id=index, content="section", egress_policy=EgressPolicy.SHAREABLE) for index in range(8))
    report = ReportVersion(owner_id="owner-1", id="report-r3", sections=sections, egress_policy=EgressPolicy.SHAREABLE)
    decision = Decision(owner_id="owner-1", id="decision-r3", text="Proceed", egress_policy=EgressPolicy.SHAREABLE)
    experiment = Experiment(owner_id="owner-1", id="experiment-r3", name="Pilot", egress_policy=EgressPolicy.SHAREABLE)
    instruction = InstructionArtifact(owner_id="owner-1", id="instruction-r3", path="AGENTS.md", egress_policy=EgressPolicy.SHAREABLE)
    return (owner, idea, asset, person, organization, source, first, second, material, claim, evidence, campaign, run, report, *sections, decision, experiment, instruction)


def test_shareable_projection_covers_all_read_mcp_node_types_without_private_fields() -> None:
    nodes = _shareable_node_fixture()
    assert {node.node_type for node in nodes} == READ_MCP_NODE_TYPES

    private_keys = {"owner_id", "provenance", "private_notes", "contact", "details", "input_snapshot", "results", "scope", "metadata"}
    for node in nodes:
        projection = project_shareable(node)
        assert projection, node.node_type
        assert not private_keys.intersection(projection)
        if node.node_type is NodeType.REPORT_VERSION:
            assert all(not private_keys.intersection(section) for section in projection["sections"])


def test_local_only_and_explicit_projection_fail_closed_for_all_read_mcp_node_types() -> None:
    authorization_time = utc_now() + timedelta(seconds=1)
    for node in _shareable_node_fixture():
        local = replace(node, egress_policy=EgressPolicy.LOCAL_ONLY)
        assert project_shareable(local) == {}

        explicit = replace(node, egress_policy=EgressPolicy.EXPLICIT)
        campaign = ResearchCampaign(
            owner_id="owner-1",
            id=f"campaign-explicit-{node.node_type.value}",
            purpose="Explicit projection",
            target_idea_id=str(node.id),
            allowed_categories=("*",),
            expires_at=authorization_time + timedelta(days=1),
        ).approve(approved_at=authorization_time)
        registry = CampaignAuthorizationRegistry.from_campaign(campaign)
        projection = project_shareable(
            explicit,
            authorization=campaign.authorization_snapshot,
            campaign=campaign,
            authorization_registry=registry,
            at=authorization_time + timedelta(seconds=1),
        )
        assert projection, node.node_type
