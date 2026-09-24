from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from dots.founder_graph import (
    Claim,
    EgressPolicy,
    Evidence,
    Idea,
    NodeType,
    Organization,
    PersonAsset,
    Provenance,
    ReportSection,
    ReportVersion,
    ResearchCampaign,
    ResearchRun,
    Source,
    SourceRevision,
    ContentChunk,
    Status,
    project_shareable,
)
from dots.founder_graph_mcp_write import McpWriteError, McpWriteSurface
from dots.founder_graph_write import InMemoryGraphWriteService


def _surface() -> tuple[InMemoryGraphWriteService, McpWriteSurface]:
    writes = InMemoryGraphWriteService("owner-1")
    return writes, McpWriteSurface(writes)


def _seed_report_dependencies(
    writes: InMemoryGraphWriteService,
    *,
    campaign_id: str = "campaign-1",
    run_id: str = "run-1",
    claim_id: str = "claim-1",
    evidence_id: str = "evidence-1",
) -> ResearchRun:
    campaign = ResearchCampaign(owner_id="owner-1", id=campaign_id, purpose="Evaluate a founder idea").approve(
        approved_at=datetime(2030, 1, 1, tzinfo=timezone.utc)
    )
    writes.put_node(campaign, idempotency_key=f"{campaign_id}-write")
    run = ResearchRun(
        owner_id="owner-1",
        id=run_id,
        campaign_id=campaign.id,
        authorization_snapshot_id=campaign.authorization_snapshot_id,
        authorization_revision=campaign.authorization_revision,
        input_snapshot={"query": "market"},
        model_snapshot="model-1",
    )
    writes.put_node(run, idempotency_key=f"{run_id}-write")
    claim = Claim(owner_id="owner-1", id=claim_id, text="A supported fact", confidence=0.9)
    writes.put_node(claim, idempotency_key=f"{claim_id}-write")
    evidence = Evidence(
        owner_id="owner-1",
        id=evidence_id,
        material_id="material-1",
        claim_id=claim.id,
        excerpt="Evidence excerpt",
    )
    writes.put_node(evidence, idempotency_key=f"{evidence_id}-write")
    return run


def _report_arguments(
    *,
    run_ids: list[str],
    claim_id: str = "claim-1",
    evidence_id: str = "evidence-1",
    parent_id: str | None = None,
    idempotency_key: str = "report-with-references",
) -> dict[str, object]:
    arguments: dict[str, object] = {
        "sections": [
            {
                "id": index,
                "content": f"section-{index}",
                "claim_ids": [claim_id],
                "evidence_ids": [evidence_id],
            }
            for index in range(8)
        ],
        "run_ids": run_ids,
        "evidence_ids": [evidence_id],
        "financial_formulas": {"break_even": "fixed_cost / margin"},
        "decision_criteria": {"stop": "stop if evidence fails"},
        "status": "final",
        "idempotency_key": idempotency_key,
    }
    if parent_id is not None:
        arguments["parent_id"] = parent_id
    return arguments


def test_write_surface_exposes_confirmed_person_merge_tool() -> None:
    _writes, surface = _surface()
    definitions = surface.tool_definitions()

    assert [definition["name"] for definition in definitions] == [
        "capture_idea",
        "capture_person",
        "capture_organization",
        "append_claim",
        "link_entities",
        "save_research_report",
        "record_decision",
        "record_correction",
        "confirm_person_merge",
    ]
    assert all(definition["readOnly"] is False for definition in definitions)


def test_capture_person_and_organization_are_idempotent_and_keep_relationships_explicit() -> None:
    writes, surface = _surface()
    person_args = {
        "name": "Potential partner",
        "description": "Met at a founder event",
        "contact": {"email": "person@example.test", "phone": "+81-90-0000-0000"},
        "private_notes": "Follow up after the prototype review.",
        "idempotency_key": "person-1",
    }
    first_person = surface.call("capture_person", person_args, owner_id="owner-1")
    replay_person = surface.call("capture_person", person_args, owner_id="owner-1")
    organization_args = {
        "name": "Potential Partner Inc.",
        "description": "A prospective collaboration partner",
        "egress_policy": "shareable",
        "idempotency_key": "organization-1",
    }
    first_organization = surface.call("capture_organization", organization_args, owner_id="owner-1")
    replay_organization = surface.call("capture_organization", organization_args, owner_id="owner-1")

    person = writes.get_node(first_person.target_id)
    organization = writes.get_node(first_organization.target_id)
    assert isinstance(person, PersonAsset)
    assert person.owner_id == "owner-1"
    assert person.egress_policy is EgressPolicy.LOCAL_ONLY
    assert dict(person.contact) == person_args["contact"]
    assert person.private_notes == person_args["private_notes"]
    assert isinstance(organization, Organization)
    assert organization.owner_id == "owner-1"
    assert organization.egress_policy is EgressPolicy.SHAREABLE
    assert project_shareable(organization)["name"] == organization.name
    assert replay_person.target_id == first_person.target_id
    assert replay_person.replayed is True
    assert replay_organization.target_id == first_organization.target_id
    assert replay_organization.replayed is True
    assert writes.relations() == ()
    assert len(writes.nodes()) == 2
    assert len(writes.audit_events()) == 2


def test_confirm_person_merge_requires_explicit_confirmation_and_is_idempotent() -> None:
    writes, surface = _surface()
    winner = PersonAsset(owner_id="owner-1", id="person-winner", name="Aki Ito", contact={"email": "winner@example.test"})
    loser = PersonAsset(owner_id="owner-1", id="person-loser", name="Aki Ito", contact={"email": "loser@example.test"})
    evidence = Evidence(owner_id="owner-1", id="merge-evidence", material_id="synthetic-card", claim_id="synthetic-claim")
    writes.put_node(winner, idempotency_key="seed-winner")
    writes.put_node(loser, idempotency_key="seed-loser")
    writes.put_node(evidence, idempotency_key="seed-evidence")
    arguments = {
        "winner_person_id": winner.id,
        "loser_person_id": loser.id,
        "confirmation": "confirmed",
        "evidence_ids": [evidence.id],
        "idempotency_key": "confirm-namesake-merge",
    }

    with pytest.raises(McpWriteError) as rejected:
        surface.call("confirm_person_merge", {**arguments, "confirmation": "proposed"}, owner_id="owner-1")
    assert rejected.value.code == "invalid_input"
    assert writes.get_node(loser.id).status is Status.ACTIVE
    assert writes.relations() == ()

    first = surface.call("confirm_person_merge", arguments, owner_id="owner-1")
    replay = surface.call("confirm_person_merge", arguments, owner_id="owner-1")

    assertion = writes.get_node(first.target_id)
    assert first.target_type == "relation_assertion"
    assert replay.target_id == first.target_id
    assert replay.replayed is True
    assert writes.get_node(winner.id).status is Status.ACTIVE
    assert writes.get_node(loser.id).status is Status.ARCHIVED
    assert assertion.predicate.value == "MERGED_INTO"
    assert assertion.status.value == "confirmed"
    assert assertion.source_id == loser.id
    assert assertion.target_id == winner.id
    assert assertion.evidence_ids == (evidence.id,)
    assert "winner@example.test" not in str(first)
    assert "loser@example.test" not in str(first)
    assert len(tuple(node for node in writes.nodes() if node.node_type.value == "relation_assertion")) == 1


def test_capture_person_rejects_non_local_egress_before_persistence() -> None:
    writes, surface = _surface()

    with pytest.raises(McpWriteError) as error:
        surface.call(
            "capture_person",
            {
                "name": "Private contact",
                "contact": {"email": "person@example.test"},
                "egress_policy": "shareable",
                "idempotency_key": "person-shareable",
            },
            owner_id="owner-1",
        )

    assert error.value.code == "invalid_input"
    assert writes.nodes() == ()
    assert writes.audit_events() == ()

    with pytest.raises(McpWriteError) as error:
        surface.call(
            "capture_person",
            {"name": "No private data", "egress_policy": "explicit", "idempotency_key": "person-explicit"},
            owner_id="owner-1",
        )
    assert error.value.code == "invalid_input"
    assert writes.nodes() == ()


@pytest.mark.parametrize("tool_name", ["capture_person", "capture_organization"])
def test_contact_capture_rejects_unknown_fields_and_wrong_owner(tool_name: str) -> None:
    _writes, surface = _surface()
    arguments = {"name": "Contact", "idempotency_key": f"{tool_name}-unknown", "unexpected": True}

    with pytest.raises(McpWriteError) as unknown:
        surface.call(tool_name, arguments, owner_id="owner-1")
    assert unknown.value.code == "invalid_input"

    with pytest.raises(McpWriteError) as owner:
        surface.call(tool_name, {"name": "Contact", "idempotency_key": f"{tool_name}-owner"}, owner_id="owner-2")
    assert owner.value.code == "owner_mismatch"


def test_capture_idea_and_append_claim_are_idempotent() -> None:
    writes, surface = _surface()
    idea_args = {"title": "A founder idea", "summary": "Test", "idempotency_key": "idea-1"}
    first = surface.call("capture_idea", idea_args, owner_id="owner-1")
    replay = surface.call("capture_idea", idea_args, owner_id="owner-1")
    claim_args = {"text": "A supported fact", "confidence": 0.9, "idempotency_key": "claim-1"}
    claim_first = surface.call("append_claim", claim_args, owner_id="owner-1")
    claim_replay = surface.call("append_claim", claim_args, owner_id="owner-1")

    assert first.target_id == replay.target_id
    assert replay.replayed is True
    assert claim_first.target_id == claim_replay.target_id
    assert len(writes.nodes()) == 4
    assert len(writes.audit_events()) == 2


def test_capture_idea_persists_source_and_source_revision_atomically() -> None:
    writes, surface = _surface()

    receipt = surface.call(
        "capture_idea",
        {
            "title": "Conversation idea",
            "source_text": "The raw founder conversation.",
            "idempotency_key": "idea-with-source",
        },
        owner_id="owner-1",
    )

    idea = writes.get_node(receipt.target_id)
    sources = tuple(node for node in writes.nodes() if isinstance(node, Source))
    revisions = tuple(node for node in writes.nodes() if isinstance(node, SourceRevision))

    assert isinstance(idea, Idea)
    assert idea.source_text == ""
    assert len(sources) == 1
    assert len(revisions) == 1
    assert sources[0].current_revision_id == revisions[0].id
    assert revisions[0].source_id == sources[0].id
    assert revisions[0].content == "The raw founder conversation."
    assert idea.provenance.source_id == revisions[0].id

    replay = surface.call(
        "capture_idea",
        {
            "title": "Conversation idea",
            "source_text": "The raw founder conversation.",
            "idempotency_key": "idea-with-source",
        },
        owner_id="owner-1",
    )
    assert replay.replayed is True
    chunks = tuple(node for node in writes.nodes() if isinstance(node, ContentChunk))
    assert len(chunks) == 1
    assert replay.source_revision_id == revisions[0].id
    assert replay.content_chunk_ids == tuple(chunk.id for chunk in chunks)
    assert len(writes.nodes()) == 4


def test_link_entities_and_record_correction_use_domain_contracts() -> None:
    writes, surface = _surface()
    person = PersonAsset(owner_id="owner-1", id="person-1", name="Potential partner")
    evidence = Evidence(owner_id="owner-1", id="evidence-1", material_id="material-1", claim_id="claim-1")
    writes.put_node(person, idempotency_key="person")
    writes.put_node(evidence, idempotency_key="evidence")
    idea_receipt = surface.call(
        "capture_idea",
        {"title": "Partner idea", "idempotency_key": "idea"},
        owner_id="owner-1",
    )
    link = surface.call(
        "link_entities",
        {
            "source_id": person.id,
            "target_id": idea_receipt.target_id,
            "relation": "CAN_CONTRIBUTE_TO",
            "evidence_ids": [evidence.id],
            "confidence": 0.8,
            "expires_at": "2027-01-01T00:00:00Z",
            "idempotency_key": "link",
        },
        owner_id="owner-1",
    )
    correction = surface.call(
        "record_correction",
        {"previous_id": idea_receipt.target_id, "title": "Corrected idea", "idempotency_key": "correction"},
        owner_id="owner-1",
    )

    assert link.target_type == "relationship"
    assert writes.get_node(idea_receipt.target_id).title == "Partner idea"
    assert writes.get_node(correction.target_id).supersedes_id == idea_receipt.target_id


def test_save_report_and_decision_are_owner_scoped() -> None:
    writes, surface = _surface()
    sections = [{"id": index, "content": f"section-{index}"} for index in range(8)]
    report = surface.call(
        "save_research_report",
        {"sections": sections, "idempotency_key": "report"},
        owner_id="owner-1",
    )
    decision = surface.call(
        "record_decision",
        {"text": "Keep testing", "report_ids": [report.target_id], "idempotency_key": "decision"},
        owner_id="owner-1",
    )

    assert writes.get_node(report.target_id).owner_id == "owner-1"
    assert writes.get_node(decision.target_id).report_ids == (report.target_id,)
    with pytest.raises(McpWriteError) as denied:
        surface.call("record_decision", {"text": "No", "idempotency_key": "denied"}, owner_id="owner-2")
    assert denied.value.code == "owner_mismatch"


def test_save_research_report_resolves_same_owner_references() -> None:
    writes, surface = _surface()
    run = _seed_report_dependencies(writes)
    arguments = _report_arguments(run_ids=[run.id])

    first = surface.call("save_research_report", arguments, owner_id="owner-1")
    replay = surface.call("save_research_report", arguments, owner_id="owner-1")

    assert first.target_type == NodeType.REPORT_VERSION.value
    assert replay.target_id == first.target_id
    assert replay.replayed is True
    assert writes.get_node(first.target_id).run_ids == (run.id,)
    assert len(writes.audit_events()) == 5


def test_save_research_report_accepts_two_runs_from_one_campaign() -> None:
    writes, surface = _surface()
    campaign = ResearchCampaign(
        owner_id="owner-1",
        id="campaign-two-runs",
        purpose="Compare two research strategies",
        trial_budget=2,
    ).approve(approved_at=datetime(2030, 1, 1, tzinfo=timezone.utc))
    writes.put_node(campaign, idempotency_key="campaign-two-runs-approve")
    run_ids: list[str] = []
    for index, at in enumerate((datetime(2030, 1, 1, 1, tzinfo=timezone.utc), datetime(2030, 1, 1, 2, tzinfo=timezone.utc)), 1):
        next_campaign = campaign.register_run(at=at)
        writes.put_node(
            next_campaign,
            idempotency_key=f"campaign-two-runs-register-{index}",
            expected_revision=campaign.aggregate_revision,
        )
        campaign = next_campaign
        run = ResearchRun(
            owner_id="owner-1",
            id=f"run-two-{index}",
            campaign_id=campaign.id,
            authorization_snapshot_id=campaign.authorization_snapshot_id,
            authorization_revision=campaign.authorization_revision,
            input_snapshot={"query": f"strategy-{index}"},
            model_snapshot="model-1",
        )
        writes.put_node(run, idempotency_key=f"run-two-{index}")
        run_ids.append(run.id)

    claim = Claim(owner_id="owner-1", id="claim-two-runs", text="A comparable fact", confidence=0.9)
    writes.put_node(claim, idempotency_key="claim-two-runs")
    evidence = Evidence(
        owner_id="owner-1",
        id="evidence-two-runs",
        material_id="material-two-runs",
        claim_id=claim.id,
        excerpt="Comparison evidence",
    )
    writes.put_node(evidence, idempotency_key="evidence-two-runs")

    arguments = _report_arguments(run_ids=run_ids, claim_id=claim.id, evidence_id=evidence.id)
    receipt = surface.call("save_research_report", arguments, owner_id="owner-1")

    assert writes.get_node(receipt.target_id).run_ids == tuple(run_ids)
    assert campaign.run_count == campaign.trial_budget == 2


def test_save_research_report_rejects_run_after_campaign_scope_change() -> None:
    writes, surface = _surface()
    run = _seed_report_dependencies(writes)
    approved = writes.get_node(run.campaign_id)
    changed = approved.change_scope(
        {"topic": "different strategy"},
        at=datetime(2030, 1, 2, tzinfo=timezone.utc),
    )
    writes.put_node(
        changed,
        idempotency_key="campaign-scope-change",
        expected_revision=approved.aggregate_revision,
    )
    before_nodes = writes.nodes()
    before_audit = writes.audit_events()

    with pytest.raises(McpWriteError) as error:
        surface.call(
            "save_research_report",
            _report_arguments(run_ids=[run.id]),
            owner_id="owner-1",
        )

    assert error.value.code == "invalid_input"
    assert writes.nodes() == before_nodes
    assert writes.audit_events() == before_audit


def test_save_research_report_rejects_expired_campaign_authorization() -> None:
    writes, surface = _surface()
    now = datetime.now(timezone.utc)
    campaign = ResearchCampaign(
        owner_id="owner-1",
        id="campaign-expired-report",
        purpose="Expired report campaign",
        expires_at=now - timedelta(days=1),
        provenance=Provenance(occurred_at=now - timedelta(days=3)),
    ).approve(
        approved_at=now - timedelta(days=2),
        provenance=Provenance(occurred_at=now - timedelta(days=2)),
    )
    writes.put_node(campaign, idempotency_key="campaign-expired-report")
    run = ResearchRun(
        owner_id="owner-1",
        id="run-expired-report",
        campaign_id=campaign.id,
        authorization_snapshot_id=campaign.authorization_snapshot_id,
        authorization_revision=campaign.authorization_revision,
        input_snapshot={"query": "expired"},
        model_snapshot="model-1",
    )
    writes.put_node(run, idempotency_key="run-expired-report")
    claim = Claim(owner_id="owner-1", id="claim-expired-report", text="Expired fact", confidence=0.7)
    writes.put_node(claim, idempotency_key="claim-expired-report")
    evidence = Evidence(
        owner_id="owner-1",
        id="evidence-expired-report",
        material_id="material-expired-report",
        claim_id=claim.id,
        excerpt="Expired evidence",
    )
    writes.put_node(evidence, idempotency_key="evidence-expired-report")
    before_nodes = writes.nodes()
    before_audit = writes.audit_events()

    with pytest.raises(McpWriteError) as error:
        surface.call(
            "save_research_report",
            _report_arguments(run_ids=[run.id], claim_id=claim.id, evidence_id=evidence.id),
            owner_id="owner-1",
        )

    assert error.value.code == "invalid_input"
    assert writes.nodes() == before_nodes
    assert writes.audit_events() == before_audit


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("run_ids", ["missing-run"]),
        ("evidence_ids", ["missing-evidence"]),
        ("sections", [
            {
                "id": index,
                "content": f"section-{index}",
                "claim_ids": ["missing-claim"],
                "evidence_ids": ["evidence-1"],
            }
            for index in range(8)
        ]),
    ),
)
def test_save_research_report_rejects_missing_or_cross_owner_references(field: str, value: object) -> None:
    writes, surface = _surface()
    run = _seed_report_dependencies(writes)
    arguments = _report_arguments(run_ids=[run.id])
    arguments[field] = value
    before_nodes = writes.nodes()
    before_audit = writes.audit_events()

    with pytest.raises(McpWriteError) as error:
        surface.call("save_research_report", arguments, owner_id="owner-1")

    assert error.value.code == "invalid_input"
    assert writes.nodes() == before_nodes
    assert writes.audit_events() == before_audit


def test_save_research_report_accepts_a_same_owner_report_parent() -> None:
    writes, surface = _surface()
    run = _seed_report_dependencies(writes)
    parent = surface.call(
        "save_research_report",
        _report_arguments(run_ids=[run.id], idempotency_key="report-parent"),
        owner_id="owner-1",
    )

    child = surface.call(
        "save_research_report",
        _report_arguments(
            run_ids=[run.id],
            parent_id=parent.target_id,
            idempotency_key="report-child",
        ),
        owner_id="owner-1",
    )

    assert writes.get_node(child.target_id).parent_id == parent.target_id


@pytest.mark.parametrize("parent_id", ("missing-report-parent", "run-1"))
def test_save_research_report_rejects_missing_or_wrong_type_parent(parent_id: str) -> None:
    writes, surface = _surface()
    run = _seed_report_dependencies(writes)
    before_nodes = writes.nodes()
    before_audit = writes.audit_events()

    with pytest.raises(McpWriteError) as error:
        surface.call(
            "save_research_report",
            _report_arguments(run_ids=[run.id], parent_id=parent_id),
            owner_id="owner-1",
        )

    assert error.value.code == "invalid_input"
    assert writes.nodes() == before_nodes
    assert writes.audit_events() == before_audit


def test_save_research_report_rejects_cross_owner_report_parent() -> None:
    writes, surface = _surface()
    run = _seed_report_dependencies(writes)
    foreign_parent = ReportVersion(
        owner_id="owner-2",
        id="foreign-report-parent",
        sections=tuple(ReportSection(owner_id="owner-2", id=index, content="foreign") for index in range(8)),
    )
    writes._nodes[foreign_parent.id] = foreign_parent
    before_nodes = writes.nodes()
    before_audit = writes.audit_events()

    with pytest.raises(McpWriteError) as error:
        surface.call(
            "save_research_report",
            _report_arguments(run_ids=[run.id], parent_id=foreign_parent.id),
            owner_id="owner-1",
        )

    assert error.value.code == "invalid_input"
    assert writes.nodes() == before_nodes
    assert writes.audit_events() == before_audit


def test_save_research_report_rejects_mixed_campaign_runs() -> None:
    writes, surface = _surface()
    first_run = _seed_report_dependencies(writes)
    second_run = _seed_report_dependencies(
        writes,
        campaign_id="campaign-2",
        run_id="run-2",
        claim_id="claim-2",
        evidence_id="evidence-2",
    )
    arguments = _report_arguments(run_ids=[first_run.id, second_run.id], claim_id="claim-1", evidence_id="evidence-1")
    before_nodes = writes.nodes()
    before_audit = writes.audit_events()

    with pytest.raises(McpWriteError) as error:
        surface.call("save_research_report", arguments, owner_id="owner-1")

    assert error.value.code == "invalid_input"
    assert writes.nodes() == before_nodes
    assert writes.audit_events() == before_audit


def test_save_research_report_rejects_section_evidence_for_another_claim() -> None:
    writes, surface = _surface()
    run = _seed_report_dependencies(writes)
    other_claim = Claim(owner_id="owner-1", id="claim-2", text="An unrelated fact", confidence=0.8)
    writes.put_node(other_claim, idempotency_key="claim-2-write")
    other_evidence = Evidence(
        owner_id="owner-1",
        id="evidence-2",
        material_id="material-2",
        claim_id=other_claim.id,
        excerpt="Unrelated evidence",
    )
    writes.put_node(other_evidence, idempotency_key="evidence-2-write")
    arguments = _report_arguments(run_ids=[run.id], evidence_id=other_evidence.id)
    arguments["sections"] = [
        {
            "id": index,
            "content": f"section-{index}",
            "claim_ids": ["claim-1"],
            "evidence_ids": [other_evidence.id],
        }
        for index in range(8)
    ]
    before_nodes = writes.nodes()
    before_audit = writes.audit_events()

    with pytest.raises(McpWriteError) as error:
        surface.call("save_research_report", arguments, owner_id="owner-1")

    assert error.value.code == "invalid_input"
    assert writes.nodes() == before_nodes
    assert writes.audit_events() == before_audit


def test_unsupported_write_and_payload_conflict_fail_closed() -> None:
    _writes, surface = _surface()
    with pytest.raises(McpWriteError, match="purpose-limited"):
        surface.call("delete", {}, owner_id="owner-1")

    surface.call("capture_idea", {"title": "Original", "idempotency_key": "same"}, owner_id="owner-1")
    with pytest.raises(McpWriteError) as conflict:
        surface.call("capture_idea", {"title": "Changed", "idempotency_key": "same"}, owner_id="owner-1")
    assert conflict.value.code == "idempotency_conflict"
