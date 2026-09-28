"""Pure validation boundary for proposed relations derived from an IdeaBrief."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Literal

from .founder_graph import (
    DomainValidationError,
    Evidence,
    NodeType,
    Provenance,
    ProvenanceOrigin,
    RelationAssertion,
    RelationAssertionBasis,
    RelationType,
    RelationshipStatus,
    Status,
)
from .idea_brief import IdeaBriefVersion
from .idea_brief_read_projection import brief_section_has_readable_body
from .markdown_report_projection import (
    find_unique_visible_quote,
    has_visible_markdown_content,
    project_markdown_report,
)


MAX_MANIFEST_BYTES = 64 * 1024
MAX_CANDIDATES = 64
MAX_EVIDENCE_IDS = 32
MAX_SUPPORT_QUOTE_CHARS = 1200

_SEMANTIC_PREDICATES = frozenset({
    RelationType.REUSES,
    RelationType.ADDRESSES,
    RelationType.DERIVED_FROM,
    RelationType.EVALUATED_BY,
    RelationType.REQUIRES_CAPABILITY,
    RelationType.CLASSIFIED_AS,
    RelationType.SERVES,
    RelationType.COMPETES_WITH,
    RelationType.DEPENDS_ON,
    RelationType.MERGED_INTO,
})
_MANIFEST_FIELDS = frozenset({
    "version", "idea_id", "candidates",
})
_CANDIDATE_FIELDS = frozenset({
    "source_id", "target_id", "predicate", "basis", "support", "evidence_ids",
})


class CandidateManifestValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CandidateEntityRef:
    id: str
    owner_id: str
    kind: NodeType

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip() or len(self.id) > 200:
            raise CandidateManifestValidationError("endpoint reference ID is invalid")
        if not isinstance(self.owner_id, str) or not self.owner_id.strip() or len(self.owner_id) > 200:
            raise CandidateManifestValidationError("endpoint reference owner is invalid")
        try:
            kind = self.kind if isinstance(self.kind, NodeType) else NodeType(self.kind)
        except (TypeError, ValueError):
            raise CandidateManifestValidationError("endpoint reference kind is invalid") from None
        object.__setattr__(self, "id", self.id.strip())
        object.__setattr__(self, "owner_id", self.owner_id.strip())
        object.__setattr__(self, "kind", kind)


@dataclass(frozen=True, slots=True)
class CandidateSupport:
    """Transient anchor; quote offsets are half-open character positions."""

    kind: Literal["quote", "section"]
    quote: str | None
    char_start: int | None
    char_end: int | None
    section_index: int | None


@dataclass(frozen=True, slots=True)
class ValidatedRelationCandidate:
    candidate_id: str
    assertion: RelationAssertion
    support: CandidateSupport


@dataclass(frozen=True, slots=True)
class ValidatedRelationCandidateManifest:
    idea_id: str
    brief_id: str
    brief_revision: int
    brief_markdown_sha256: str
    candidates: tuple[ValidatedRelationCandidate, ...]


def _fail(message: str) -> None:
    raise CandidateManifestValidationError(message)


def _exact_fields(value: object, expected: frozenset[str], name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != expected:
        _fail(f"{name} fields do not match the candidate manifest contract")
    return value


def _identifier(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > 200:
        _fail(f"{name} must be a non-empty short identifier")
    return value


def _canonical_json(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError):
        _fail("manifest must contain JSON-compatible values")
    if len(encoded) > MAX_MANIFEST_BYTES:
        _fail("manifest exceeds the 64 KiB limit")
    return encoded


def _support_anchor(
    raw_support: object,
    *,
    markdown: str,
    projection,
) -> CandidateSupport:
    if not isinstance(raw_support, Mapping):
        _fail("candidate support must be a quote or canonical section")
    if set(raw_support) == {"quote"}:
        quote = raw_support["quote"]
        if not isinstance(quote, str) or not quote.strip() or len(quote) > MAX_SUPPORT_QUOTE_CHARS:
            _fail("support quote must contain 1 through 1200 characters")
        offsets = find_unique_visible_quote(markdown, quote)
        if offsets is None:
            _fail("support must be an exact unique visible quote in the latest Brief")
        start, end = offsets
        section_index: int | None = None
        if projection.heading_status != "ambiguous":
            section_index = next((
                heading.section_index
                for heading in projection.headings
                if heading.body_offset <= start and end <= heading.end_offset
            ), None)
        return CandidateSupport("quote", quote, start, end, section_index)
    if set(raw_support) == {"section_index"}:
        section_index = raw_support["section_index"]
        if type(section_index) is not int or not 0 <= section_index < 8:
            _fail("canonical section index must be an integer from 0 through 7")
        if projection.heading_status == "ambiguous":
            _fail("canonical section cannot be resolved from ambiguous Markdown headings")
        matches = tuple(item for item in projection.headings if item.section_index == section_index)
        if len(matches) != 1 or not has_visible_markdown_content(
            markdown, matches[0].body_offset, matches[0].end_offset,
        ):
            _fail("support must identify a non-empty canonical section")
        return CandidateSupport("section", None, None, None, section_index)
    _fail("candidate support must contain exactly one quote or section index")


def _is_source_grounded_evidence(evidence: Evidence, owner_id: str) -> bool:
    return evidence.owner_id == owner_id and evidence.status is Status.ACTIVE and evidence.content_chunk_id is not None


def _resolve_predicate(value: object) -> RelationType:
    if not isinstance(value, str):
        _fail("candidate semantic predicate must be a string")
    try:
        predicate = RelationType(value)
    except ValueError:
        _fail("candidate semantic predicate is not supported")
    if predicate not in _SEMANTIC_PREDICATES:
        _fail("candidate semantic predicate is not supported by the Brief contract")
    return predicate


def validate_relation_candidate_manifest(
    manifest: Mapping[str, object],
    *,
    latest_brief: IdeaBriefVersion,
    current_idea_id: str,
    entity_refs: Mapping[str, CandidateEntityRef],
    source_grounded_evidence: Mapping[str, Evidence],
) -> ValidatedRelationCandidateManifest:
    """Validate owner-scoped sources; an explicit empty list means reviewed with no proposals.

    Callers that omit a manifest have not completed review and must leave the job
    pending. Writers still recheck Brief and Evidence transactionally.
    """
    if not isinstance(latest_brief, IdeaBriefVersion):
        _fail("latest Brief is required")
    current_idea_id = _identifier(current_idea_id, "current Idea ID")
    if latest_brief.based_on_idea_id != current_idea_id:
        _fail("latest Brief does not match the current Idea")
    if not latest_brief.report_markdown:
        _fail("latest Brief Markdown is required for candidate support")
    markdown = latest_brief.report_markdown
    projection = project_markdown_report(markdown)
    actual_markdown_hash = sha256(markdown.encode("utf-8")).hexdigest()

    _canonical_json(manifest)
    raw_manifest = _exact_fields(manifest, _MANIFEST_FIELDS, "manifest")
    if type(raw_manifest["version"]) is not int or raw_manifest["version"] != 1:
        _fail("manifest version must be 1")
    if _identifier(raw_manifest["idea_id"], "manifest Idea ID") != current_idea_id:
        _fail("manifest Idea does not match the current Idea")
    raw_candidates = raw_manifest["candidates"]
    if not isinstance(raw_candidates, (list, tuple)) or len(raw_candidates) > MAX_CANDIDATES:
        _fail("candidate count must be between 0 and 64")
    if not isinstance(entity_refs, Mapping) or not isinstance(source_grounded_evidence, Mapping):
        _fail("resolved endpoint and Evidence maps are required")

    candidates: list[ValidatedRelationCandidate] = []
    semantic_keys: set[tuple[str, RelationType, str]] = set()
    for raw_candidate in raw_candidates:
        raw = _exact_fields(raw_candidate, _CANDIDATE_FIELDS, "candidate")
        source_id = _identifier(raw["source_id"], "source ID")
        target_id = _identifier(raw["target_id"], "target ID")
        if source_id == target_id:
            _fail("candidate endpoints must be different")
        source_ref = entity_refs.get(source_id)
        target_ref = entity_refs.get(target_id)
        if (
            not isinstance(source_ref, CandidateEntityRef)
            or source_ref.id != source_id
            or source_ref.owner_id != latest_brief.owner_id
            or not isinstance(target_ref, CandidateEntityRef)
            or target_ref.id != target_id
            or target_ref.owner_id != latest_brief.owner_id
        ):
            _fail("candidate endpoint is missing from the owner-scoped endpoint map")
        if current_idea_id not in {source_id, target_id}:
            _fail("candidate must include the current Idea endpoint")
        idea_ref = source_ref if source_id == current_idea_id else target_ref
        if idea_ref.kind is not NodeType.IDEA:
            _fail("current Idea endpoint must resolve to an Idea")

        predicate = _resolve_predicate(raw["predicate"])
        basis_value = raw["basis"]
        try:
            basis = RelationAssertionBasis(basis_value)
        except (TypeError, ValueError):
            _fail("candidate basis must be brief_hypothesis or external_evidence")
        evidence_values = raw["evidence_ids"]
        if not isinstance(evidence_values, (list, tuple)) or len(evidence_values) > MAX_EVIDENCE_IDS:
            _fail("candidate Evidence IDs must be a bounded sequence")
        evidence_ids = tuple(_identifier(item, "Evidence ID") for item in evidence_values)
        if len(evidence_ids) != len(set(evidence_ids)):
            _fail("candidate Evidence IDs must not contain duplicates")
        support = _support_anchor(raw["support"], markdown=markdown, projection=projection)

        if basis is RelationAssertionBasis.BRIEF_HYPOTHESIS:
            if evidence_ids:
                _fail("Brief hypotheses cannot cite Evidence")
            if NodeType.IDEA not in {source_ref.kind, target_ref.kind}:
                _fail("Brief hypothesis relation must include an Idea endpoint")
        else:
            if not evidence_ids:
                _fail("external_evidence candidates require source-grounded Evidence")
            section_index = support.section_index
            if section_index is None:
                _fail("external_evidence candidates require a canonical Brief section anchor")
            brief_section = latest_brief.sections[section_index]
            if (
                not brief_section_has_readable_body(latest_brief, section_index)
                or not set(evidence_ids).issubset(brief_section.evidence_ids)
            ):
                _fail("external Evidence must belong to the selected Brief section's Evidence")
            for evidence_id in evidence_ids:
                evidence = source_grounded_evidence.get(evidence_id)
                if not isinstance(evidence, Evidence) or evidence.id != evidence_id:
                    _fail("candidate Evidence does not exist in the resolved graph context")
                if evidence.owner_id != latest_brief.owner_id:
                    _fail("candidate Evidence owner does not match the Brief")
                if not _is_source_grounded_evidence(evidence, latest_brief.owner_id):
                    _fail("candidate Evidence must be active source-grounded Evidence")

        semantic_key = (source_id, predicate, target_id)
        if semantic_key in semantic_keys:
            _fail("manifest contains a duplicate semantic relation")
        semantic_keys.add(semantic_key)

        canonical_candidate = {
            "idea_id": current_idea_id,
            "brief_id": latest_brief.id,
            "brief_revision": latest_brief.revision,
            "brief_markdown_sha256": actual_markdown_hash,
            "source_id": source_id,
            "target_id": target_id,
            "predicate": predicate.value,
            "basis": basis.value,
            "support": {
                "kind": support.kind,
                "quote": support.quote,
                "char_start": support.char_start,
                "char_end": support.char_end,
                "section_index": support.section_index,
            },
            "evidence_ids": sorted(evidence_ids),
        }
        digest = sha256(_canonical_json(canonical_candidate)).hexdigest()
        candidate_id = f"relation-candidate-{digest[:32]}"
        family_hash = sha256(
            f"{latest_brief.owner_id}\0{source_id}\0{predicate.value}\0{target_id}".encode("utf-8")
        ).hexdigest()[:32]
        try:
            assertion = RelationAssertion(
                id=candidate_id,
                owner_id=latest_brief.owner_id,
                source_id=source_id,
                target_id=target_id,
                source_kind=source_ref.kind,
                target_kind=target_ref.kind,
                predicate=predicate,
                assertion_family_id=f"relation-family-{family_hash}",
                status=RelationshipStatus.PROPOSED,
                basis=basis,
                evidence_ids=tuple(sorted(evidence_ids)),
                valid_from=latest_brief.created_at,
                based_on_brief_id=latest_brief.id,
                based_on_brief_section_index=support.section_index,
                provenance=Provenance(
                    actor="dots_candidate_manifest",
                    operation="validate_candidate",
                    origin=ProvenanceOrigin.IMPORT,
                    target_id=candidate_id,
                    source_id=latest_brief.id,
                    occurred_at=latest_brief.created_at,
                    idempotency_key=candidate_id,
                ),
            )
        except DomainValidationError as error:
            _fail(f"candidate is outside the RelationAssertion domain: {error}")
        candidates.append(ValidatedRelationCandidate(candidate_id, assertion, support))

    candidates.sort(key=lambda item: item.candidate_id)
    return ValidatedRelationCandidateManifest(
        idea_id=current_idea_id,
        brief_id=latest_brief.id,
        brief_revision=latest_brief.revision,
        brief_markdown_sha256=actual_markdown_hash,
        candidates=tuple(candidates),
    )
