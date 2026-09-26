from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from dots.founder_graph import (
    Asset,
    Claim,
    EgressPolicy,
    Evidence,
    Idea,
    MaterialKind,
    NodeType,
    Organization,
    PersonAsset,
    Provenance,
    ReportSection,
    ReportVersion,
    RelationAssertion,
    RelationAssertionEdgeType,
    RelationType,
    Relationship,
    RelationshipStatus,
    ResearchCampaign,
    ResearchRun,
    Source,
    SourceRevision,
    ContentChunk,
    Status,
    project_shareable,
)
from dots.founder_graph_mcp_write import McpWriteError, McpWriteSurface
from dots.founder_graph_mcp import McpReadError, McpReadSurface
from dots.founder_graph_read import GraphReadService
from dots.founder_graph_neo4j_write import PersistedNodeReference
from dots.founder_graph_write import InMemoryGraphWriteService, WriteReceipt
from dots.idea_brief import IdeaBriefSection, IdeaBriefVersion


def _surface() -> tuple[InMemoryGraphWriteService, McpWriteSurface]:
    writes = InMemoryGraphWriteService("owner-1")
    return writes, McpWriteSurface(writes)


def test_capture_asset_is_metadata_only_create_only_and_owner_scoped() -> None:
    writes, surface = _surface()
    arguments = {"name": "Synthetic kit", "kind": "artifact", "summary": "Safe short summary", "egress_policy": "shareable", "idempotency_key": "asset-key"}
    first = surface.call("capture_asset", arguments, owner_id="owner-1")
    replay = surface.call("capture_asset", arguments, owner_id="owner-1")

    assert first.target_id == replay.target_id and replay.replayed
    asset = writes.get_node(first.target_id)
    assert isinstance(asset, Asset)
    assert asset.details == {} and asset.description == "Safe short summary"
    assert asset.egress_policy is EgressPolicy.SHAREABLE
    local_receipt = surface.call("capture_asset", {"name": "Local kit", "kind": "equipment", "idempotency_key": "asset-local"}, owner_id="owner-1")
    reader = McpReadSurface(GraphReadService(writes))
    with pytest.raises(McpReadError):
        reader.call("fetch", {"id": local_receipt.target_id}, owner_id="owner-1")
    projected = reader.call("fetch", {"id": first.target_id}, owner_id="owner-1")
    assert set(projected["fields"]) == {"name", "kind", "description", "status"}
    assert projected["id"] == first.target_id
    assert projected["fields"]["description"] == "Safe short summary"
    assert "details" not in str(projected)
    for field in ("id", "owner_id", "details", "body", "content", "source_text", "contact", "private_notes", "locator", "provenance"):
        value = {"private": "x"} if field in {"details", "contact", "provenance"} else "private"
        with pytest.raises(McpWriteError, match="Unknown tool arguments"):
            surface.call("capture_asset", {"name": "Rejected", "kind": "artifact", "idempotency_key": f"reject-{field}", field: value}, owner_id="owner-1")
    with pytest.raises(McpWriteError, match="different payload"):
        surface.call("capture_asset", {**arguments, "name": "Changed"}, owner_id="owner-1")
    with pytest.raises(McpWriteError, match="owner"):
        surface.call("capture_asset", arguments, owner_id="owner-2")
    assert len(writes.audit_events()) == 2


def _capture_link_evidence(
    writes: InMemoryGraphWriteService, claim_id: str, *, key: str,
    egress_policy: EgressPolicy = EgressPolicy.LOCAL_ONLY,
) -> Evidence:
    source = Source(owner_id=writes.owner_id, id=f"source-{key}", title="Synthetic source",
                    kind=MaterialKind.WEB, locator=f"https://example.test/{key}",
                    current_revision_id=f"revision-{key}", revision=1)
    revision = SourceRevision(owner_id=writes.owner_id, id=source.current_revision_id,
                              source_id=source.id, content="Synthetic source text", locator=source.locator)
    receipt = writes.capture_source(source, revision, idempotency_key=f"source-{key}")
    evidence_receipt = writes.capture_evidence(
        claim_id, receipt.content_chunk_ids[0], egress_policy=egress_policy,
        idempotency_key=f"evidence-{key}",
    )
    return writes.get_node(evidence_receipt.target_id)


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


def _save_researched_brief(
    writes: InMemoryGraphWriteService,
    idea: Idea,
    evidence: Evidence,
) -> IdeaBriefVersion:
    now = datetime.now(timezone.utc)
    campaign = ResearchCampaign(
        owner_id=idea.owner_id,
        id=f"campaign-for-{idea.id}",
        purpose="Synthetic relation evidence",
        target_idea_id=idea.id,
        allowed_categories=("idea.summary",),
        trial_budget=1,
        expires_at=now + timedelta(hours=1),
        created_at=now - timedelta(minutes=10),
        provenance=Provenance(
            actor="synthetic-test", operation="create", target_id=f"campaign-for-{idea.id}",
            occurred_at=now - timedelta(minutes=10),
        ),
    )
    writes.put_node(campaign, idempotency_key=f"seed-{campaign.id}")
    approved = campaign.approve(
        approved_at=now - timedelta(minutes=5),
        provenance=Provenance(
            actor="synthetic-test", operation="approve", target_id=campaign.id,
            occurred_at=now - timedelta(minutes=5),
        ),
    )
    writes.put_node(
        approved,
        expected_revision=campaign.aggregate_revision,
        idempotency_key=f"approve-{campaign.id}",
    )
    run = ResearchRun(
        owner_id=idea.owner_id,
        id=f"run-for-{idea.id}",
        campaign_id=campaign.id,
        authorization_snapshot_id=approved.authorization_snapshot_id,
        authorization_revision=approved.authorization_revision,
        input_snapshot={"query": "synthetic"},
        model_snapshot="synthetic-model",
        sources=("synthetic-source",),
        evidence_ids=(evidence.id,),
        results={"summary": "synthetic"},
        status=Status.COMPLETED,
        started_at=now - timedelta(minutes=3),
        finished_at=now - timedelta(minutes=2),
    )
    writes.record_research_run(
        run,
        expected_campaign_revision=approved.aggregate_revision,
        idempotency_key=f"record-{run.id}",
    )
    brief = IdeaBriefVersion(
        owner_id=idea.owner_id,
        idea_lineage_root_id=idea.id,
        based_on_idea_id=idea.id,
        research_run_ids=(run.id,),
        sections=tuple(
            IdeaBriefSection(index=index, content=f"Synthetic section {index}", evidence_ids=(evidence.id,))
            for index in range(8)
        ),
    )
    writes.save_idea_brief(brief, expected_latest_revision=None, idempotency_key=f"save-{brief.id}")
    return brief


def test_write_surface_exposes_confirmed_person_merge_tool() -> None:
    _writes, surface = _surface()
    definitions = surface.tool_definitions()

    assert [definition["name"] for definition in definitions] == [
        "capture_idea",
        "capture_source",
        "capture_person",
        "capture_organization",
        "capture_asset",
        "append_claim",
        "capture_evidence",
        "link_entities",
        "save_research_report",
        "record_decision",
        "record_correction",
        "confirm_person_merge",
    ]
    assert all(definition["readOnly"] is False for definition in definitions)


def test_capture_source_saves_only_short_local_web_material_and_replays() -> None:
    writes, surface = _surface()
    args = {"url": "https://example.org/research", "title": "Public source",
            "summary": "A short self-authored summary.", "idempotency_key": "source-1"}
    first = surface.call("capture_source", args, owner_id="owner-1")
    replay = surface.call("capture_source", args, owner_id="owner-1")
    saved_source = writes.get_node(first.target_id)
    saved_revision = writes.get_node(first.source_revision_id)
    assert first.target_type == NodeType.SOURCE.value
    assert replay.replayed is True and replay.target_id == first.target_id
    assert saved_source.kind.value == "web" and saved_source.egress_policy is EgressPolicy.LOCAL_ONLY
    assert saved_revision.content == args["summary"] and saved_revision.locator == args["url"]
    assert all(writes.get_node(chunk_id).egress_policy is EgressPolicy.LOCAL_ONLY for chunk_id in first.content_chunk_ids)
    assert not any(isinstance(node, Idea) for node in writes.nodes())
    tool = next(item for item in surface.tool_definitions() if item["name"] == "capture_source")
    assert set(tool["inputSchema"]["properties"]) == {"url", "title", "summary", "idempotency_key"}


@pytest.mark.parametrize("url", ["file:///tmp/private", "https://user:password@example.org/x", "https:///missing-host"])
def test_capture_source_rejects_unsafe_or_non_http_urls(url: str) -> None:
    writes, surface = _surface()
    with pytest.raises(McpWriteError):
        surface.call("capture_source", {"url": url, "title": "Source", "summary": "Summary", "idempotency_key": "bad"}, owner_id="owner-1")
    assert writes.nodes() == ()


def test_capture_evidence_allows_shareable_policy_only_for_shareable_claim_and_projects_no_lineage() -> None:
    writes, surface = _surface()
    schema = next(item["inputSchema"] for item in surface.tool_definitions() if item["name"] == "capture_evidence")
    assert schema["properties"]["egress_policy"]["enum"] == ["local_only", "shareable"]
    person_schema = next(item["inputSchema"] for item in surface.tool_definitions() if item["name"] == "capture_person")
    assert person_schema["properties"]["egress_policy"]["enum"] == ["local_only"]
    source = surface.call("capture_source", {
        "url": "https://example.test/private", "title": "Private source",
        "summary": "Private body phrase", "idempotency_key": "evidence-source",
    }, owner_id="owner-1")
    claim = surface.call("append_claim", {
        "text": "Shareable claim", "egress_policy": "shareable", "idempotency_key": "shareable-claim",
    }, owner_id="owner-1")
    receipt = surface.call("capture_evidence", {
        "claim_id": claim.target_id, "content_chunk_id": source.content_chunk_ids[0],
        "egress_policy": "shareable", "idempotency_key": "shareable-evidence",
    }, owner_id="owner-1")
    evidence = writes.get_node(receipt.target_id)
    assert evidence.egress_policy is EgressPolicy.SHAREABLE
    projection = McpReadSurface(GraphReadService(writes)).call(
        "fetch", {"id": receipt.target_id}, owner_id="owner-1",
    )
    assert projection["id"] == receipt.target_id
    serialized = str(projection)
    assert all(value not in serialized for value in (
        "Private body phrase", "https://example.test/private", source.source_revision_id,
        source.content_chunk_ids[0],
    ))
    assert not {"excerpt", "locator", "claim_id", "source_revision_id", "content_chunk_id"} & set(projection["fields"])
    for private_field in ("excerpt", "locator", "source_text"):
        with pytest.raises(McpWriteError):
            surface.call("capture_evidence", {
                "claim_id": claim.target_id, "content_chunk_id": source.content_chunk_ids[0],
                "idempotency_key": f"reject-{private_field}", private_field: "private",
            }, owner_id="owner-1")
    with pytest.raises(McpWriteError):
        surface.call("capture_evidence", {
            "claim_id": claim.target_id, "content_chunk_id": source.content_chunk_ids[0],
            "egress_policy": "unknown", "idempotency_key": "reject-policy",
        }, owner_id="owner-1")


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
    assert person.provenance.operation == "capture_person"
    assert person.provenance.target_id == person.id
    assert dict(person.contact) == person_args["contact"]
    assert person.private_notes == person_args["private_notes"]
    assert isinstance(organization, Organization)
    assert organization.owner_id == "owner-1"
    assert organization.egress_policy is EgressPolicy.SHAREABLE
    assert organization.provenance.operation == "capture_organization"
    assert organization.provenance.target_id == organization.id
    assert project_shareable(organization)["name"] == organization.name
    reader = McpReadSurface(GraphReadService(writes))
    organization_projection = reader.call("fetch", {"id": organization.id}, owner_id="owner-1")
    assert organization_projection["id"] == organization.id
    assert "provenance" not in str(organization_projection)
    with pytest.raises(McpReadError):
        reader.call("fetch", {"id": person.id}, owner_id="owner-1")
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
    other_person = PersonAsset(owner_id="owner-1", id="person-2", name="Another partner")
    claim = Claim(owner_id="owner-1", id="claim-1", text="Synthetic claim")
    writes.put_node(person, idempotency_key="person")
    writes.put_node(other_person, idempotency_key="person-2")
    writes.put_node(claim, idempotency_key="claim")
    evidence = _capture_link_evidence(writes, claim.id, key="link-entities")
    idea_receipt = surface.call(
        "capture_idea",
        {"title": "Partner idea", "idempotency_key": "idea"},
        owner_id="owner-1",
    )
    link = surface.call(
        "link_entities",
        {
            "source_id": person.id,
            "target_id": other_person.id,
            "relation": "INTRODUCED_BY",
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

    assertion = writes.get_node(link.target_id)
    assert link.target_type == NodeType.RELATION_ASSERTION.value
    assert isinstance(assertion, RelationAssertion)
    assert assertion.source_kind is NodeType.PERSON
    assert assertion.target_kind is NodeType.PERSON
    assert assertion.status is RelationshipStatus.PROPOSED
    assert assertion.egress_policy is EgressPolicy.LOCAL_ONLY
    assert assertion.evidence_ids == (evidence.id,)
    assert not any(isinstance(node, Relationship) for node in writes.nodes())
    assert writes.get_node(idea_receipt.target_id).title == "Partner idea"
    assert writes.get_node(correction.target_id).supersedes_id == idea_receipt.target_id


def test_link_entities_retries_same_formal_assertion_without_duplicate_edges() -> None:
    writes, surface = _surface()
    first = PersonAsset(
        owner_id="owner-1", id="introduced-person-1", name="First", egress_policy=EgressPolicy.SHAREABLE,
    )
    second = PersonAsset(
        owner_id="owner-1", id="introduced-person-2", name="Second", egress_policy=EgressPolicy.SHAREABLE,
    )
    claim = Claim(
        owner_id="owner-1", id="link-claim", text="Synthetic", confidence=0.8,
        egress_policy=EgressPolicy.SHAREABLE,
    )
    for node in (first, second, claim):
        writes.put_node(node, idempotency_key=f"seed-{node.id}")
    evidence = _capture_link_evidence(writes, claim.id, key="shareable-link", egress_policy=EgressPolicy.SHAREABLE)
    arguments = {
        "source_id": first.id,
        "target_id": second.id,
        "relation": RelationType.INTRODUCED_BY.value,
        "status": RelationshipStatus.INFERRED.value,
        "confidence": 0.7,
        "expires_at": "2099-01-01T00:00:00Z",
        "evidence_ids": [evidence.id],
        "egress_policy": EgressPolicy.SHAREABLE.value,
        "idempotency_key": "same-formal-link",
    }

    first_receipt = surface.call("link_entities", arguments, owner_id="owner-1")
    replay = surface.call("link_entities", arguments, owner_id="owner-1")
    assertion = writes.get_node(first_receipt.target_id)

    assert first_receipt.target_type == NodeType.RELATION_ASSERTION.value
    assert replay.replayed is True and replay.target_id == first_receipt.target_id
    assert assertion.egress_policy is EgressPolicy.SHAREABLE
    assert all(writes.get_node(node_id).egress_policy is EgressPolicy.SHAREABLE for node_id in (first.id, second.id, evidence.id))
    assert sum(1 for node in writes.nodes() if isinstance(node, RelationAssertion)) == 1
    assert writes.structural_edges().count((assertion.id, RelationAssertionEdgeType.ASSERTS_FROM.value, first.id)) == 1
    assert writes.structural_edges().count((assertion.id, RelationAssertionEdgeType.ASSERTS_TO.value, second.id)) == 1


@pytest.mark.parametrize("private_component", ["evidence", "endpoint"])
def test_link_entities_rejects_shareable_assertion_with_local_only_component_without_writes(
    private_component: str,
) -> None:
    writes, surface = _surface()
    first = PersonAsset(
        owner_id="owner-1", id=f"private-check-first-{private_component}", name="First",
        egress_policy=EgressPolicy.LOCAL_ONLY if private_component == "endpoint" else EgressPolicy.SHAREABLE,
    )
    second = PersonAsset(
        owner_id="owner-1", id=f"private-check-second-{private_component}", name="Second",
        egress_policy=EgressPolicy.SHAREABLE,
    )
    claim = Claim(
        owner_id="owner-1", id=f"private-check-claim-{private_component}", text="Synthetic", confidence=0.8,
        egress_policy=EgressPolicy.SHAREABLE,
    )
    evidence = Evidence(
        owner_id="owner-1", id=f"private-check-evidence-{private_component}", material_id="private-check-material",
        claim_id=claim.id,
        egress_policy=EgressPolicy.LOCAL_ONLY if private_component == "evidence" else EgressPolicy.SHAREABLE,
    )
    for node in (first, second, claim, evidence):
        writes.put_node(node, idempotency_key=f"seed-{node.id}")
    before_nodes = writes.nodes()
    before_edges = writes.structural_edges()
    before_audit = writes.audit_events()

    with pytest.raises(McpWriteError):
        surface.call("link_entities", {
            "source_id": first.id,
            "target_id": second.id,
            "relation": RelationType.INTRODUCED_BY.value,
            "status": RelationshipStatus.INFERRED.value,
            "confidence": 0.7,
            "expires_at": "2099-01-01T00:00:00Z",
            "evidence_ids": [evidence.id],
            "egress_policy": EgressPolicy.SHAREABLE.value,
            "idempotency_key": f"shareable-private-component-{private_component}",
        }, owner_id="owner-1")

    assert writes.nodes() == before_nodes
    assert writes.structural_edges() == before_edges
    assert writes.audit_events() == before_audit


@pytest.mark.parametrize("status", ["confirmed", "rejected", "superseded", "expired"])
def test_link_entities_rejects_non_model_generated_status_without_writes(status: str) -> None:
    writes, surface = _surface()
    first = PersonAsset(owner_id="owner-1", id="status-person-1", name="First")
    second = PersonAsset(owner_id="owner-1", id="status-person-2", name="Second")
    for node in (first, second):
        writes.put_node(node, idempotency_key=f"seed-{node.id}")
    before_nodes = writes.nodes()
    before_edges = writes.structural_edges()
    before_audit = writes.audit_events()

    with pytest.raises(McpWriteError):
        surface.call("link_entities", {
            "source_id": first.id, "target_id": second.id,
            "relation": "USES_SKILL", "status": status,
            "idempotency_key": f"bad-status-{status}",
        }, owner_id="owner-1")

    assert writes.nodes() == before_nodes
    assert writes.structural_edges() == before_edges
    assert writes.audit_events() == before_audit


def test_link_entities_schema_is_closed_and_requires_idea_brief_pair() -> None:
    writes, surface = _surface()
    definition = next(tool for tool in surface.tool_definitions() if tool["name"] == "link_entities")
    schema = definition["inputSchema"]
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {
        "source_id", "target_id", "relation", "status", "confidence", "expires_at",
        "evidence_ids", "egress_policy", "based_on_brief_id", "based_on_brief_section_index", "idempotency_key",
    }
    assert "evidence_ids" in schema["required"]
    assert schema["properties"]["evidence_ids"]["minItems"] == 1
    assert schema["properties"]["status"]["enum"] == ["proposed", "inferred"]
    assert definition["annotations"]["destructiveHint"] is False

    idea = Idea(owner_id="owner-1", id="idea-link-no-brief", title="Synthetic idea")
    person = PersonAsset(owner_id="owner-1", id="person-link-no-brief", name="Synthetic person")
    writes.put_node(idea, idempotency_key="seed-idea-link")
    writes.put_node(person, idempotency_key="seed-person-link")
    before = writes.nodes()
    with pytest.raises(McpWriteError):
        surface.call("link_entities", {
            "source_id": idea.id, "target_id": person.id, "relation": "REUSES",
            "evidence_ids": ["not-used"], "idempotency_key": "idea-link-without-brief",
        }, owner_id="owner-1")
    assert writes.nodes() == before


def test_link_entities_passes_exact_idea_brief_evidence_to_formal_adapter() -> None:
    writes, surface = _surface()
    idea = Idea(owner_id="owner-1", id="idea-link-researched", title="Synthetic idea")
    claim = Claim(owner_id="owner-1", id="claim-link-researched", text="Synthetic claim", confidence=0.8)
    for node in (idea, claim):
        writes.put_node(node, idempotency_key=f"seed-{node.id}")
    evidence = _capture_link_evidence(writes, claim.id, key="idea-link-researched")
    brief = _save_researched_brief(writes, idea, evidence)

    receipt = surface.call("link_entities", {
        "source_id": idea.id,
        "target_id": claim.id,
        "relation": RelationType.ADDRESSES.value,
        "status": RelationshipStatus.INFERRED.value,
        "evidence_ids": [evidence.id],
        "based_on_brief_id": brief.id,
        "based_on_brief_section_index": 1,
        "idempotency_key": "idea-link-researched",
    }, owner_id="owner-1")

    assertion = writes.get_node(receipt.target_id)
    assert isinstance(assertion, RelationAssertion)
    assert assertion.based_on_brief_id == brief.id
    assert assertion.based_on_brief_section_index == 1
    assert assertion.evidence_ids == (evidence.id,)


def test_link_entities_adapter_rejects_idea_brief_that_does_not_contain_evidence() -> None:
    writes, surface = _surface()
    idea = Idea(owner_id="owner-1", id="idea-link-evidence-check", title="Synthetic idea")
    claim = Claim(owner_id="owner-1", id="claim-link-evidence-check", text="Synthetic claim", confidence=0.8)
    cited = Evidence(owner_id="owner-1", id="evidence-cited", material_id="material-cited", claim_id=claim.id)
    uncited = Evidence(owner_id="owner-1", id="evidence-uncited", material_id="material-uncited", claim_id=claim.id)
    for node in (idea, claim, cited, uncited):
        writes.put_node(node, idempotency_key=f"seed-{node.id}")
    brief = _save_researched_brief(writes, idea, cited)
    before = (writes.nodes(), writes.structural_edges(), writes.audit_events())

    with pytest.raises(McpWriteError):
        surface.call("link_entities", {
            "source_id": idea.id,
            "target_id": claim.id,
            "relation": RelationType.ADDRESSES.value,
            "status": RelationshipStatus.INFERRED.value,
            "evidence_ids": [uncited.id],
            "based_on_brief_id": brief.id,
            "based_on_brief_section_index": 1,
            "idempotency_key": "idea-link-uncited-evidence",
        }, owner_id="owner-1")

    assert (writes.nodes(), writes.structural_edges(), writes.audit_events()) == before


def test_link_entities_uses_persisted_node_kinds_for_idea_brief_gate() -> None:
    class Neo4jShapedAdapter:
        owner_id = "owner-1"

        def __init__(self) -> None:
            self.saved: RelationAssertion | None = None
            self.nodes = {
                "persisted-idea": PersistedNodeReference(
                    id="persisted-idea", owner_id=self.owner_id, node_type=NodeType.IDEA,
                    revision=1, fields={},
                ),
                "persisted-claim": PersistedNodeReference(
                    id="persisted-claim", owner_id=self.owner_id, node_type=NodeType.CLAIM,
                    revision=1, fields={},
                ),
            }

        def get_node(self, node_id: str):
            return self.nodes.get(node_id)

        def save_relation_assertion(self, assertion, *, expected_family_revision, idempotency_key):
            self.saved = assertion
            return WriteReceipt(
                operation="save_relation_assertion", target_id=assertion.id,
                target_type=NodeType.RELATION_ASSERTION.value, revision=1,
                idempotency_key=idempotency_key,
            )

    adapter = Neo4jShapedAdapter()
    surface = McpWriteSurface(adapter)  # type: ignore[arg-type]
    base_arguments = {
        "source_id": "persisted-idea", "target_id": "persisted-claim",
        "relation": RelationType.ADDRESSES.value, "evidence_ids": ["persisted-evidence"],
        "idempotency_key": "persisted-idea-link",
    }

    with pytest.raises(McpWriteError):
        surface.call("link_entities", base_arguments, owner_id="owner-1")
    assert adapter.saved is None

    receipt = surface.call("link_entities", {
        **base_arguments,
        "based_on_brief_id": "persisted-brief",
        "based_on_brief_section_index": 6,
    }, owner_id="owner-1")

    assert receipt.target_type == NodeType.RELATION_ASSERTION.value
    assert adapter.saved is not None
    assert adapter.saved.based_on_brief_id == "persisted-brief"
    assert adapter.saved.based_on_brief_section_index == 6


def test_link_entities_rejects_unknown_fields_before_mutation() -> None:
    writes, surface = _surface()
    first = PersonAsset(owner_id="owner-1", id="unknown-person-1", name="First")
    second = PersonAsset(owner_id="owner-1", id="unknown-person-2", name="Second")
    for node in (first, second):
        writes.put_node(node, idempotency_key=f"seed-{node.id}")
    before = (writes.nodes(), writes.structural_edges(), writes.audit_events())
    with pytest.raises(McpWriteError):
        surface.call("link_entities", {
            "source_id": first.id, "target_id": second.id, "relation": "USES_SKILL",
            "idempotency_key": "unknown-field", "status_override": "confirmed",
        }, owner_id="owner-1")
    assert (writes.nodes(), writes.structural_edges(), writes.audit_events()) == before


def test_link_entities_fails_closed_when_adapter_has_no_formal_writer() -> None:
    class LegacyAdapter:
        owner_id = "owner-1"
        legacy_called = False

        def get_node(self, _node_id: str):
            return None

        def link_entities(self, *_args, **_kwargs):
            self.legacy_called = True

    adapter = LegacyAdapter()
    surface = McpWriteSurface(adapter)  # type: ignore[arg-type]

    with pytest.raises(McpWriteError) as error:
        surface.call("link_entities", {
            "source_id": "legacy-source", "target_id": "legacy-target",
            "relation": "USES_SKILL", "idempotency_key": "legacy-no-fallback",
        }, owner_id="owner-1")

    assert error.value.code == "unavailable"
    assert adapter.legacy_called is False


def test_link_entities_preserves_required_network_expiry_constraint() -> None:
    writes, surface = _surface()
    first = PersonAsset(owner_id="owner-1", id="expiry-person-1", name="First")
    second = PersonAsset(owner_id="owner-1", id="expiry-person-2", name="Second")
    for node in (first, second):
        writes.put_node(node, idempotency_key=f"seed-{node.id}")
    before = (writes.nodes(), writes.structural_edges(), writes.audit_events())

    with pytest.raises(McpWriteError):
        surface.call("link_entities", {
            "source_id": first.id, "target_id": second.id,
            "relation": RelationType.INTRODUCED_BY.value,
            "confidence": 0.8,
            "idempotency_key": "network-without-expiry",
        }, owner_id="owner-1")

    assert (writes.nodes(), writes.structural_edges(), writes.audit_events()) == before


@pytest.mark.parametrize("evidence_value", [None, []], ids=["omitted", "empty"])
def test_link_entities_requires_evidence_without_mutation(evidence_value: object) -> None:
    writes, surface = _surface()
    first = PersonAsset(owner_id="owner-1", id=f"evidence-person-1-{evidence_value}", name="First")
    second = PersonAsset(owner_id="owner-1", id=f"evidence-person-2-{evidence_value}", name="Second")
    for node in (first, second):
        writes.put_node(node, idempotency_key=f"seed-{node.id}")
    before = (writes.nodes(), writes.structural_edges(), writes.audit_events())
    arguments = {
        "source_id": first.id, "target_id": second.id,
        "relation": RelationType.INTRODUCED_BY.value,
        "confidence": 0.8, "expires_at": "2099-01-01T00:00:00Z",
        "idempotency_key": f"missing-evidence-{evidence_value}",
    }
    if evidence_value is not None:
        arguments["evidence_ids"] = evidence_value

    with pytest.raises(McpWriteError):
        surface.call("link_entities", arguments, owner_id="owner-1")

    assert (writes.nodes(), writes.structural_edges(), writes.audit_events()) == before


def test_link_entities_rejects_invalid_expiry_timestamp_without_mutation() -> None:
    writes, surface = _surface()
    first = PersonAsset(owner_id="owner-1", id="invalid-expiry-person-1", name="First")
    second = PersonAsset(owner_id="owner-1", id="invalid-expiry-person-2", name="Second")
    for node in (first, second):
        writes.put_node(node, idempotency_key=f"seed-{node.id}")
    before = (writes.nodes(), writes.structural_edges(), writes.audit_events())

    with pytest.raises(McpWriteError) as error:
        surface.call("link_entities", {
            "source_id": first.id,
            "target_id": second.id,
            "relation": RelationType.INTRODUCED_BY.value,
            "confidence": 0.8,
            "expires_at": "not-a-valid-timestamp",
            "evidence_ids": ["synthetic-evidence"],
            "idempotency_key": "invalid-expiry-time",
        }, owner_id="owner-1")

    assert error.value.code == "invalid_input"
    assert (writes.nodes(), writes.structural_edges(), writes.audit_events()) == before


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
