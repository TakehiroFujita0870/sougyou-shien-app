from __future__ import annotations

from datetime import datetime, timedelta, timezone

from dots.founder_graph import (
    Claim,
    EgressPolicy,
    Facet,
    Idea,
    MaterialKind,
    Provenance,
    RelationAssertion,
    ResearchCampaign,
    ResearchRun,
    Source,
    SourceRevision,
    Status,
)
from dots.founder_graph_mcp_write import McpWriteError, McpWriteSurface
from dots.founder_graph_write import InMemoryGraphWriteService
from dots.idea_brief import IdeaBriefSection, IdeaBriefVersion


def _seed_researched_idea_and_evidence(writes: InMemoryGraphWriteService):
    now = datetime.now(timezone.utc)
    idea = Idea(owner_id=writes.owner_id, id="facet-researched-idea", title="Synthetic researched idea",
                egress_policy=EgressPolicy.SHAREABLE)
    writes.put_node(idea, idempotency_key="facet-researched-idea")
    claim = Claim(owner_id=writes.owner_id, id="facet-researched-claim", text="Synthetic supported fact",
                  confidence=0.9, egress_policy=EgressPolicy.SHAREABLE)
    writes.put_node(claim, idempotency_key="facet-researched-claim")
    source = Source(owner_id=writes.owner_id, id="facet-researched-source", title="Synthetic source",
                    kind=MaterialKind.WEB, locator="https://example.test/researched-facet",
                    current_revision_id="facet-researched-source-revision", revision=1,
                    egress_policy=EgressPolicy.SHAREABLE)
    source_revision = SourceRevision(owner_id=writes.owner_id, id="facet-researched-source-revision",
                                     source_id=source.id, content="Synthetic source content",
                                     locator=source.locator, egress_policy=EgressPolicy.SHAREABLE)
    source_receipt = writes.capture_source(source, source_revision, idempotency_key="facet-researched-source")
    evidence_receipt = writes.capture_evidence(
        claim.id, source_receipt.content_chunk_ids[0], egress_policy=EgressPolicy.SHAREABLE,
        idempotency_key="facet-researched-evidence",
    )
    evidence = writes.get_node(evidence_receipt.target_id)
    campaign = ResearchCampaign(
        owner_id=writes.owner_id, id="facet-researched-campaign", purpose="Synthetic Facet research",
        target_idea_id=idea.id, allowed_categories=("idea.summary",), trial_budget=1,
        expires_at=now + timedelta(hours=1), created_at=now - timedelta(minutes=10),
        provenance=Provenance(actor="synthetic-test", operation="create", target_id="facet-researched-campaign",
                              occurred_at=now - timedelta(minutes=10)),
    )
    writes.put_node(campaign, idempotency_key="facet-researched-campaign")
    approved = campaign.approve(approved_at=now - timedelta(minutes=5))
    writes.put_node(approved, expected_revision=campaign.aggregate_revision,
                    idempotency_key="facet-researched-campaign-approval")
    run = ResearchRun(
        owner_id=writes.owner_id, id="facet-researched-run", campaign_id=campaign.id,
        authorization_snapshot_id=approved.authorization_snapshot_id,
        authorization_revision=approved.authorization_revision, input_snapshot={"query": "synthetic"},
        model_snapshot="synthetic-model", sources=(source.locator,), evidence_ids=(evidence.id,),
        results={"summary": "Synthetic researched result"}, status=Status.COMPLETED,
        started_at=now - timedelta(minutes=3), finished_at=now - timedelta(minutes=2),
    )
    writes.record_research_run(
        run, expected_campaign_revision=approved.aggregate_revision, idempotency_key="facet-researched-run",
    )
    brief = IdeaBriefVersion(
        owner_id=writes.owner_id, idea_lineage_root_id=idea.id, based_on_idea_id=idea.id,
        research_run_ids=(run.id,), egress_policy=EgressPolicy.SHAREABLE,
        sections=tuple(IdeaBriefSection(index=index, content=f"Synthetic section {index}",
                                        evidence_ids=(evidence.id,)) for index in range(8)),
    )
    writes.save_idea_brief(brief, expected_latest_revision=None, idempotency_key="facet-researched-brief")
    return idea, evidence, brief


def test_capture_facet_is_idempotent_and_local_by_default() -> None:
    writes = InMemoryGraphWriteService("owner-1")
    surface = McpWriteSurface(writes)
    arguments = {"namespace": "business", "value": "Bakery", "idempotency_key": "facet-local"}

    first = surface.call("capture_facet", arguments, owner_id="owner-1")
    replay = surface.call("capture_facet", arguments, owner_id="owner-1")

    facet = writes.get_node(first.target_id)
    assert isinstance(facet, Facet)
    assert facet.egress_policy is EgressPolicy.LOCAL_ONLY
    assert replay.target_id == first.target_id and replay.replayed
    assert "capture_facet" in {tool["name"] for tool in surface.tool_definitions()}


def test_facet_relation_tools_reject_missing_or_empty_evidence_before_saving() -> None:
    writes = InMemoryGraphWriteService("owner-1")
    writer = McpWriteSurface(writes)
    idea, _, brief = _seed_researched_idea_and_evidence(writes)
    first_facet = writer.call("capture_facet", {
        "namespace": "domain", "value": "Food", "idempotency_key": "evidence-facet-food",
    }, owner_id="owner-1")
    second_facet = writer.call("capture_facet", {
        "namespace": "domain", "value": "Bakery", "idempotency_key": "evidence-facet-bakery",
    }, owner_id="owner-1")
    base_arguments = {
        "classify_entity": {
            "entity_id": idea.id, "facet_id": first_facet.target_id,
            "status": "proposed", "based_on_brief_id": brief.id,
            "based_on_brief_section_index": 0,
        },
        "relate_facets": {
            "broader_facet_id": first_facet.target_id,
            "narrower_facet_id": second_facet.target_id,
            "status": "proposed",
        },
    }

    for tool_name, fields in base_arguments.items():
        for evidence_value in (None, []):
            key = f"reject-{tool_name}-evidence-{evidence_value is not None}"
            arguments = {**fields, "idempotency_key": key}
            if evidence_value is not None:
                arguments["evidence_ids"] = evidence_value
            before_audit = len(writes.audit_events())

            try:
                writer.call(tool_name, arguments, owner_id="owner-1")
            except McpWriteError as error:
                assert error.code == "invalid_input"
            else:
                raise AssertionError(f"{tool_name} accepted {evidence_value!r} evidence_ids")

            assert len(writes.audit_events()) == before_audit
            relation_id = writer._command_id("relation-assertion", key)
            assert writes.get_node(relation_id) is None


def test_facet_relation_tools_accept_proposed_relations_with_evidence() -> None:
    writes = InMemoryGraphWriteService("owner-1")
    writer = McpWriteSurface(writes)
    idea, evidence, brief = _seed_researched_idea_and_evidence(writes)
    first_facet = writer.call("capture_facet", {
        "namespace": "domain", "value": "Food", "idempotency_key": "valid-facet-food",
    }, owner_id="owner-1")
    second_facet = writer.call("capture_facet", {
        "namespace": "domain", "value": "Bakery", "idempotency_key": "valid-facet-bakery",
    }, owner_id="owner-1")

    classification = writer.call("classify_entity", {
        "entity_id": idea.id, "facet_id": first_facet.target_id,
        "evidence_ids": [evidence.id], "status": "proposed",
        "based_on_brief_id": brief.id, "based_on_brief_section_index": 0,
        "idempotency_key": "valid-proposed-classification",
    }, owner_id="owner-1")
    facet_relation = writer.call("relate_facets", {
        "broader_facet_id": first_facet.target_id,
        "narrower_facet_id": second_facet.target_id,
        "evidence_ids": [evidence.id], "status": "proposed",
        "idempotency_key": "valid-proposed-facet-relation",
    }, owner_id="owner-1")

    assert writes.get_node(classification.target_id).evidence_ids == (evidence.id,)
    assert writes.get_node(facet_relation.target_id).evidence_ids == (evidence.id,)


def test_classify_entity_supports_researched_ideas_and_relation_corrections() -> None:
    writes = InMemoryGraphWriteService("owner-1")
    writer = McpWriteSurface(writes)
    idea, evidence, brief = _seed_researched_idea_and_evidence(writes)
    facet = writer.call("capture_facet", {
        "namespace": "domain", "value": "Food", "egress_policy": "shareable", "idempotency_key": "facet-research-food",
    }, owner_id="owner-1")
    args = {
        "entity_id": idea.id, "facet_id": facet.target_id, "evidence_ids": [evidence.id],
        "status": "inferred", "egress_policy": "shareable", "based_on_brief_id": brief.id,
        "based_on_brief_section_index": 3,
    }
    first = writer.call("classify_entity", {**args, "idempotency_key": "classify-researched-idea"}, owner_id="owner-1")
    corrected = writer.call("classify_entity", {
        **args, "supersedes_id": first.target_id, "expected_family_revision": 1,
        "idempotency_key": "correct-classification",
    }, owner_id="owner-1")

    assertion = writes.get_node(corrected.target_id)
    assert isinstance(assertion, RelationAssertion)
    assert assertion.based_on_brief_id == brief.id and assertion.based_on_brief_section_index == 3
    assert assertion.assertion_family_id == writes.get_node(first.target_id).assertion_family_id
    assert assertion.revision == 2 and assertion.supersedes_id == first.target_id

    try:
        writer.call("classify_entity", {
            "entity_id": idea.id, "facet_id": facet.target_id, "evidence_ids": [evidence.id],
            "status": "inferred", "egress_policy": "shareable", "based_on_brief_section_index": 4,
            "supersedes_id": corrected.target_id, "expected_family_revision": 2,
            "idempotency_key": "reject-partial-brief-correction",
        }, owner_id="owner-1")
    except McpWriteError as error:
        assert "both Brief reference fields" in str(error)
    else:
        raise AssertionError("A partial Brief reference correction was accepted")

    inherited = writer.call("classify_entity", {
        "entity_id": idea.id, "facet_id": facet.target_id, "evidence_ids": [evidence.id],
        "status": "inferred", "egress_policy": "shareable",
        "supersedes_id": corrected.target_id, "expected_family_revision": 2,
        "idempotency_key": "inherit-brief-correction",
    }, owner_id="owner-1")
    inherited_assertion = writes.get_node(inherited.target_id)
    assert inherited_assertion.based_on_brief_id == brief.id
    assert inherited_assertion.based_on_brief_section_index == 3

    tool = next(item for item in writer.tool_definitions() if item["name"] == "classify_entity")
    assert {"based_on_brief_id", "based_on_brief_section_index", "supersedes_id", "expected_family_revision"} <= set(
        tool["inputSchema"]["properties"]
    )

    asset = writer.call("capture_asset", {
        "name": "Synthetic asset", "kind": "artifact", "egress_policy": "shareable",
        "idempotency_key": "asset-without-brief-gate",
    }, owner_id="owner-1")
    try:
        writer.call("classify_entity", {
            **args, "entity_id": asset.target_id, "idempotency_key": "reject-brief-on-asset",
        }, owner_id="owner-1")
    except McpWriteError as error:
        assert "Brief" in str(error) or "brief" in str(error)
    else:
        raise AssertionError("Asset classification must not accept an Idea Brief reference")


def test_mcp_facet_taxonomy_rejects_cycles_and_retraction_removes_old_tip() -> None:
    writes = InMemoryGraphWriteService("owner-1")
    writer = McpWriteSurface(writes)
    facet_receipts = [
        writer.call("capture_facet", {
            "namespace": "domain", "value": label, "egress_policy": "shareable",
            "idempotency_key": f"facet-{label.lower()}",
        }, owner_id="owner-1")
        for label in ("A", "B", "C")
    ]
    facets = [writes.get_node(receipt.target_id) for receipt in facet_receipts]
    claim = Claim(owner_id="owner-1", id="facet-cycle-claim", text="Synthetic taxonomy evidence", confidence=0.9, egress_policy=EgressPolicy.SHAREABLE)
    writes.put_node(claim, idempotency_key="facet-cycle-claim")
    source = Source(
        owner_id="owner-1", id="facet-cycle-source", title="Public taxonomy source", kind=MaterialKind.WEB,
        locator="https://example.test/taxonomy", current_revision_id="facet-cycle-revision", revision=1,
        egress_policy=EgressPolicy.SHAREABLE,
    )
    revision = SourceRevision(
        owner_id="owner-1", id="facet-cycle-revision", source_id=source.id,
        content="Synthetic taxonomy source", locator=source.locator, egress_policy=EgressPolicy.SHAREABLE,
    )
    captured = writes.capture_source(source, revision, idempotency_key="facet-cycle-source")
    evidence = writes.capture_evidence(
        claim.id, captured.content_chunk_ids[0], egress_policy=EgressPolicy.SHAREABLE,
        idempotency_key="facet-cycle-evidence",
    )
    assert all(isinstance(facet, Facet) for facet in facets)

    first = writer.call("relate_facets", {
        "broader_facet_id": facets[0].id, "narrower_facet_id": facets[1].id,
        "evidence_ids": [evidence.target_id], "status": "inferred", "egress_policy": "shareable",
        "idempotency_key": "taxonomy-a-b",
    }, owner_id="owner-1")
    writer.call("relate_facets", {
        "broader_facet_id": facets[1].id, "narrower_facet_id": facets[2].id,
        "evidence_ids": [evidence.target_id], "status": "inferred", "egress_policy": "shareable",
        "idempotency_key": "taxonomy-b-c",
    }, owner_id="owner-1")
    try:
        writer.call("relate_facets", {
            "broader_facet_id": facets[2].id, "narrower_facet_id": facets[0].id,
            "evidence_ids": [evidence.target_id], "status": "inferred", "egress_policy": "shareable",
            "idempotency_key": "taxonomy-c-a-rejected",
        }, owner_id="owner-1")
    except Exception as error:
        assert "taxonomy" in str(error).casefold() or "relation" in str(error).casefold()
    else:
        raise AssertionError("Facet taxonomy cycle was accepted")

    writer.call("retract_relation_assertion", {
        "supersedes_id": first.target_id, "expected_family_revision": 1,
        "evidence_ids": [evidence.target_id], "egress_policy": "shareable",
        "idempotency_key": "taxonomy-a-b-retract",
    }, owner_id="owner-1")
    c_to_a = writer.call("relate_facets", {
        "broader_facet_id": facets[2].id, "narrower_facet_id": facets[0].id,
        "evidence_ids": [evidence.target_id], "status": "inferred", "egress_policy": "shareable",
        "idempotency_key": "taxonomy-c-a-after-retract",
    }, owner_id="owner-1")
    assert isinstance(writes.get_node(c_to_a.target_id), RelationAssertion)
    try:
        writer.call("relate_facets", {
            "broader_facet_id": facets[0].id, "narrower_facet_id": facets[1].id,
            "evidence_ids": [evidence.target_id], "status": "inferred", "egress_policy": "shareable",
            "idempotency_key": "taxonomy-a-b-recycle-rejected",
        }, owner_id="owner-1")
    except Exception as error:
        assert "taxonomy" in str(error).casefold() or "relation" in str(error).casefold()
    else:
        raise AssertionError("Facet taxonomy cycle was accepted after retraction")
