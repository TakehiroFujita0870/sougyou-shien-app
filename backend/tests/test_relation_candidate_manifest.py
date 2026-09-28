from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256

import pytest

from dots.founder_graph import Evidence, NodeType, RelationAssertionBasis, RelationType, Status
from dots.idea_brief import IdeaBriefSection, IdeaBriefVersion
from dots.relation_candidate_manifest import (
    CandidateEntityRef,
    CandidateManifestValidationError,
    validate_relation_candidate_manifest,
)

OWNER, IDEA = "owner-test", "idea-test"
MD = "## エグゼクティブサマリー\n\n小さな倉庫が必要です。\n"
NOW = datetime(2026, 9, 29, tzinfo=timezone.utc)


def brief(markdown=MD, evidence_ids=(), section_content="説明"):
    sections = tuple(IdeaBriefSection(
        index=i, content=section_content if i == 0 and evidence_ids else "",
        evidence_ids=evidence_ids if i == 0 else (),
    ) for i in range(8))
    return IdeaBriefVersion(
        id="brief-test", owner_id=OWNER, idea_lineage_root_id=IDEA,
        based_on_idea_id=IDEA, revision=2, supersedes_id="brief-v1",
        report_markdown=markdown, origin="prior_research_import", created_at=NOW,
        sections=sections,
    )


def evidence(owner=OWNER, status=Status.ACTIVE):
    return Evidence(
        id="evidence-test", owner_id=owner, claim_id="claim-test",
        source_revision_id="revision-test", content_chunk_id="chunk-test",
        char_start=0, char_end=4, locator="chars:0-4", content_hash="a" * 64,
        status=status,
    )


def manifest(b, *candidates):
    return {"version": 1, "idea_id": IDEA, "candidates": list(candidates)}


def candidate(**overrides):
    value = {
        "source_id": IDEA, "target_id": "asset-test",
        "predicate": RelationType.REQUIRES_CAPABILITY.value,
        "basis": "brief_hypothesis", "support": {"quote": "小さな倉庫が必要です。"},
        "evidence_ids": [],
    }
    return value | overrides


def validate(raw, b, *, refs=None, evidence_map=None, idea_id=IDEA):
    refs = refs or {
        IDEA: CandidateEntityRef(IDEA, OWNER, NodeType.IDEA),
        "asset-test": CandidateEntityRef("asset-test", OWNER, NodeType.ASSET),
    }
    return validate_relation_candidate_manifest(
        raw, latest_brief=b, current_idea_id=idea_id, entity_refs=refs,
        source_grounded_evidence=evidence_map or {},
    )


def reject(raw, b, message, **kwargs):
    with pytest.raises(CandidateManifestValidationError, match=message):
        validate(raw, b, **kwargs)


def test_hypothesis_is_proposed_unfounded_by_external_evidence_and_retry_stable():
    b = brief()
    raw = manifest(b, candidate())

    first, retry = validate(raw, b), validate(raw, b)

    assert first == retry
    item = first.candidates[0]
    assert item.candidate_id == item.assertion.id
    quote = "小さな倉庫が必要です。"
    assert item.support.quote == quote
    assert (item.support.char_start, item.support.char_end) == (
        MD.index(quote), MD.index(quote) + len(quote),
    )
    assert item.support.section_index == 0
    assert item.assertion.basis is RelationAssertionBasis.BRIEF_HYPOTHESIS
    assert (item.assertion.status.value, item.assertion.evidence_ids) == ("proposed", ())
    assert item.assertion.based_on_brief_id == b.id
    assert (first.brief_id, first.brief_revision) == (b.id, b.revision)
    assert first.brief_markdown_sha256 == sha256(MD.encode()).hexdigest()


def test_external_basis_needs_section_registered_active_source_grounded_evidence():
    ev = evidence()
    b = brief(evidence_ids=(ev.id,), section_content="")
    raw = manifest(b, candidate(
        basis="external_evidence", support={"section_index": 0}, evidence_ids=[ev.id],
    ))
    relation = validate(raw, b, evidence_map={ev.id: ev}).candidates[0].assertion
    assert relation.basis is RelationAssertionBasis.EXTERNAL_EVIDENCE
    assert relation.evidence_ids == (ev.id,) and relation.based_on_brief_section_index == 0

    for mapping, error in (
        ({}, "does not exist"),
        ({ev.id: evidence(owner="foreign")}, "owner"),
        ({ev.id: evidence(status=Status.ARCHIVED)}, "active source-grounded"),
        ({"invented": ev}, "does not exist"),
    ):
        reject(raw, b, error, evidence_map=mapping)
    reject(raw, brief(), "section's Evidence", evidence_map={ev.id: ev})
    reject(
        manifest(brief(), candidate(evidence_ids=[ev.id])), brief(), "cannot cite Evidence",
        evidence_map={ev.id: ev},
    )


def test_manifest_binds_server_created_latest_brief_and_rejects_wrong_idea_or_stale_quote():
    b = brief()
    valid = validate(manifest(b, candidate()), b)
    assert (valid.brief_id, valid.brief_revision) == (b.id, b.revision)
    assert valid.brief_markdown_sha256 == sha256(MD.encode()).hexdigest()
    reject(manifest(b, candidate()), b, "current Idea", idea_id="idea-other")
    wrong_idea = manifest(b, candidate())
    wrong_idea["idea_id"] = "old"
    reject(wrong_idea, b, "current Idea")
    changed = brief(MD.replace("小さな", "大きな"))
    reject(manifest(changed, candidate()), changed, "unique visible quote")


def test_empty_manifest_means_reviewed_with_no_relation_candidates():
    b = brief()

    validated = validate(manifest(b), b)

    assert validated.brief_id == b.id
    assert validated.candidates == ()


def test_support_must_be_exact_visible_quote_or_resolvable_nonempty_section():
    b = brief()
    for quote in ("not in Brief", "", "x" * 1201):
        reject(manifest(b, candidate(support={"quote": quote})), b, "quote")
    reject(manifest(b, candidate(support={"section_index": 1})), b, "canonical section")
    ambiguous = brief(MD + "\n## エグゼクティブサマリー\n重複")
    external = candidate(basis="external_evidence", support={"section_index": 0}, evidence_ids=["e"])
    reject(manifest(ambiguous, external), ambiguous, "ambiguous")
    empty = brief(None)
    reject(manifest(empty, candidate()), empty, "Markdown is required")


def test_malformed_or_overlong_candidates_are_rejected():
    b = brief()
    bad_endpoint = candidate(target_id="not-resolved")
    reject(manifest(b, bad_endpoint), b, "endpoint")
    reject(manifest(b, candidate(predicate="HAS_RUN")), b, "semantic predicate")
    reject(manifest(b, candidate(), candidate(support={"section_index": 0})), b, "duplicate semantic relation")
    reject(manifest(b, *(candidate() for _ in range(65))), b, "candidate count")
    malformed = manifest(b, candidate()) | {"extra": True}
    reject(malformed, b, "manifest fields")
    oversized = manifest(b, candidate()) | {"padding": "x" * 65536}
    reject(oversized, b, "64 KiB")
