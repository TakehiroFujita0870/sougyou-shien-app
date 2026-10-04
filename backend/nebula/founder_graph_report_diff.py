"""Pure, fail-closed report impact analysis for the Founder Graph.

This module intentionally sits below the persistence and transport layers.  It
accepts either the immutable domain ``ReportVersion``/``ReportSection`` values
or an already-safe mapping returned by a read adapter, and returns a new
immutable projection.  It never writes to a graph, calls a model, or mutates
the supplied report values.

The projection is deliberately narrower than the domain model.  Only chapter
content, typed chapter lists, stable reference identifiers, and withdrawn
claim metadata cross this boundary.  Private/raw fields and unknown fields are
ignored rather than copied into a future-facing diff payload.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from .founder_graph import (
    REPORT_SECTION_IDS,
    REPORT_SECTION_TITLES,
    ReportSection,
    ReportVersion,
)


class ReportDiffInputError(ValueError):
    """Raised when a report or section cannot be safely projected."""


FOUNDER_GRAPH_REPORT_CHAPTERS = tuple(
    MappingProxyType({"id": section_id, "title": REPORT_SECTION_TITLES[section_id]})
    for section_id in REPORT_SECTION_IDS
)

REPORT_CHANGE_STATUSES = MappingProxyType(
    {
        "added": "現版に追加された章",
        "changed": "前版から内容が変わった章",
        "unchanged": "前版から内容が変わっていない章",
        "removed": "現版で内容がなくなった章",
    }
)

_CHAPTER_IDS = frozenset(REPORT_SECTION_IDS)
_MISSING = object()

# These names are intentionally not copied even when they arrive inside a
# broad ``fields`` or ``metadata`` object from another adapter.  Keeping the
# deny list here makes the positive allowlist below easy to audit and means a
# new domain field cannot become an accidental egress field.
_PRIVATE_OR_RAW_FIELDS = frozenset(
    {
        "private_notes",
        "private_note",
        "contact",
        "source_text",
        "raw",
        "raw_text",
        "raw_content",
        "input_snapshot",
        "local_only",
        "secret",
        "secrets",
        "token",
        "authorization",
    }
)
_SAFE_METADATA_FIELDS = ("id", "label", "title", "name", "locator", "status", "reason")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _field(value: Any, *names: str, default: Any = _MISSING) -> Any:
    """Read a field from a domain value or safe mapping.

    Read adapters commonly nest their allowlisted payload under ``fields``;
    top-level values always win, followed by that nested mapping.  No
    arbitrary object attributes are inspected: only the domain report types
    and mappings are accepted by the public projection function.
    """

    nested = _mapping(value).get("fields", {})
    for name in names:
        if isinstance(value, Mapping) and name in value:
            return value[name]
        if not isinstance(value, Mapping) and hasattr(value, name):
            return getattr(value, name)
        if name in nested:
            return nested[name]
    return default


def _enum_value(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value


def _text(value: Any) -> str:
    value = _enum_value(value)
    return value.strip() if isinstance(value, str) else ""


def _safe_metadata_item(value: Any) -> str:
    """Convert one explicit provenance item without traversing raw fields."""

    value = _enum_value(value)
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if not isinstance(value, Mapping):
        return ""
    pieces: list[str] = []
    for key in _SAFE_METADATA_FIELDS:
        if key in _PRIVATE_OR_RAW_FIELDS:
            continue
        if key in value:
            scalar = _safe_metadata_item(value[key])
            if scalar:
                pieces.append(scalar)
    # Stable order is useful for deterministic reports and tests.  A mapping
    # can contain the same identifier under several display keys; deduplicate
    # without exposing the original mapping shape.
    return " · ".join(dict.fromkeys(pieces))


def _safe_metadata_list(*values: Any) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        if value is None:
            continue
        items = (value,) if isinstance(value, (str, int, float, bool, Mapping)) else value
        if isinstance(items, (str, Mapping)):
            items = (items,)
        try:
            iterator = iter(items)
        except TypeError:
            continue
        for item in iterator:
            normalized = _safe_metadata_item(item)
            if normalized and normalized not in result:
                result.append(normalized)
    return tuple(result)


def _safe_text_list(value: Any) -> tuple[str, ...]:
    """Normalize typed chapter text while retaining only scalar values."""

    if value is None:
        return ()
    if isinstance(value, (str, int, float, bool, Mapping)):
        value = (value,)
    try:
        iterator = iter(value)
    except TypeError:
        return ()
    result: list[str] = []
    for item in iterator:
        normalized = _safe_metadata_item(item)
        if normalized and normalized not in result:
            result.append(normalized)
    return tuple(result)


def _chapter_id(value: Any, *, fallback: Any = _MISSING) -> int | None:
    value = fallback if value is _MISSING else value
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value in _CHAPTER_IDS else None
    if isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
        return parsed if parsed in _CHAPTER_IDS else None
    return None


def _section_collection(report: ReportVersion | Mapping[str, Any]) -> tuple[tuple[Any, Any], ...]:
    raw = _field(report, "sections", "chapters")
    if raw is _MISSING:
        # An explicit section collection is required.  Treating a missing
        # collection as an empty report would hide malformed read responses.
        raise ReportDiffInputError("report sections are required")
    if isinstance(raw, Mapping):
        return tuple(raw.items())
    if isinstance(raw, (tuple, list)):
        return tuple(enumerate(raw))
    raise ReportDiffInputError("report sections must be a mapping or sequence")


def _safe_section(section: ReportSection | Mapping[str, Any], section_id: int) -> "SafeReportSection":
    if not isinstance(section, (ReportSection, SafeReportSection, Mapping)):
        raise ReportDiffInputError("report section must be a mapping or ReportSection")
    metadata = _mapping(_field(section, "metadata", default={}))
    fields = _mapping(_field(section, "fields", default={}))

    def section_value(*names: str, default: Any = _MISSING) -> Any:
        value = _field(section, *names, default=default)
        if value is not _MISSING:
            return value
        for name in names:
            if name in metadata:
                return metadata[name]
            if name in fields:
                return fields[name]
        return default

    references = _safe_metadata_list(
        section_value("references", default=()),
        section_value("reference_ids", default=()),
        section_value("referenceIds", default=()),
        section_value("citations", default=()),
        section_value("evidence_ids", default=()),
        section_value("evidenceIds", default=()),
        metadata.get("references"),
        metadata.get("reference_ids"),
        metadata.get("citations"),
        metadata.get("evidence_ids"),
        fields.get("references"),
        fields.get("reference_ids"),
        fields.get("citations"),
        fields.get("evidence_ids"),
    )
    evidence_ids = _safe_metadata_list(section_value("evidence_ids", "evidenceIds", default=()))
    claim_ids = _safe_metadata_list(section_value("claim_ids", "claimIds", default=()))
    # Evidence IDs are references even when the caller supplies only the
    # normalized section list.  Keep both fields so readers can distinguish
    # typed evidence from general citation metadata.
    references = tuple(dict.fromkeys((*references, *evidence_ids)))
    withdrawn_claims = _safe_metadata_list(
        section_value("withdrawn_claims", "withdrawnClaims", default=()),
        metadata.get("withdrawn_claims"),
        metadata.get("withdrawnClaims"),
        fields.get("withdrawn_claims"),
        fields.get("withdrawnClaims"),
    )

    return SafeReportSection(
        id=section_id,
        title=REPORT_SECTION_TITLES[section_id],
        present=section_value("present", default=True) is not False,
        content=_text(section_value("content", "summary", default="")),
        facts=_safe_text_list(section_value("facts", default=())),
        ai_inferences=_safe_text_list(section_value("ai_inferences", "aiInferences", default=())),
        unconfirmed=_safe_text_list(section_value("unconfirmed", default=())),
        owner_decisions=_safe_text_list(section_value("owner_decisions", "ownerDecisions", default=())),
        claim_ids=claim_ids,
        evidence_ids=evidence_ids,
        references=references,
        withdrawn_claims=withdrawn_claims,
    )


@dataclass(frozen=True, slots=True)
class SafeReportSection:
    """Allowlisted immutable projection of one report chapter."""

    id: int
    title: str
    present: bool
    content: str = ""
    facts: tuple[str, ...] = ()
    ai_inferences: tuple[str, ...] = ()
    unconfirmed: tuple[str, ...] = ()
    owner_decisions: tuple[str, ...] = ()
    claim_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    references: tuple[str, ...] = ()
    withdrawn_claims: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "present": self.present,
            "content": self.content,
            "facts": list(self.facts),
            "ai_inferences": list(self.ai_inferences),
            "unconfirmed": list(self.unconfirmed),
            "owner_decisions": list(self.owner_decisions),
            "claim_ids": list(self.claim_ids),
            "evidence_ids": list(self.evidence_ids),
            "references": list(self.references),
            "withdrawn_claims": list(self.withdrawn_claims),
        }


@dataclass(frozen=True, slots=True)
class SafeReportVersion:
    """Allowlisted immutable projection of a report version."""

    id: str
    status: str
    parent_id: str
    supersedes_id: str
    change_reason: str
    references: tuple[str, ...]
    withdrawn_claims: tuple[str, ...]
    run_ids: tuple[str, ...]
    sections: tuple[SafeReportSection, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "parent_id": self.parent_id,
            "supersedes_id": self.supersedes_id,
            "change_reason": self.change_reason,
            "references": list(self.references),
            "withdrawn_claims": list(self.withdrawn_claims),
            "run_ids": list(self.run_ids),
            "sections": [section.as_dict() for section in self.sections],
        }

    @property
    def section_map(self) -> Mapping[int, SafeReportSection]:
        return MappingProxyType({section.id: section for section in self.sections})


def _project_report_version(report: ReportVersion | Mapping[str, Any]) -> SafeReportVersion:
    if not isinstance(report, (ReportVersion, SafeReportVersion, Mapping)):
        raise ReportDiffInputError("report must be a mapping or ReportVersion")
    collection = _section_collection(report)
    sections_by_id: dict[int, SafeReportSection] = {}
    for key, raw_section in collection:
        if raw_section is None:
            continue
        candidate_id = _chapter_id(_field(raw_section, "id", default=_MISSING), fallback=key)
        # Reject an unclassified chapter instead of guessing its title or
        # silently treating it as one of the fixed eight chapters.
        if candidate_id is None:
            raise ReportDiffInputError("report section id must be an integer from 0 to 7")
        if candidate_id in sections_by_id:
            raise ReportDiffInputError("report sections must have unique chapter ids")
        sections_by_id[candidate_id] = _safe_section(raw_section, candidate_id)

    fields = _mapping(_field(report, "fields", default={}))
    metadata = _mapping(_field(report, "metadata", default={}))

    def report_value(*names: str, default: Any = _MISSING) -> Any:
        value = _field(report, *names, default=default)
        if value is not _MISSING:
            return value
        for name in names:
            if name in metadata:
                return metadata[name]
            if name in fields:
                return fields[name]
        return default

    references = _safe_metadata_list(
        report_value("references", default=()),
        report_value("reference_ids", default=()),
        report_value("referenceIds", default=()),
        report_value("citations", default=()),
        report_value("evidence_ids", default=()),
        report_value("evidenceIds", default=()),
        metadata.get("references"),
        metadata.get("reference_ids"),
        metadata.get("citations"),
        metadata.get("evidence_ids"),
        fields.get("references"),
        fields.get("reference_ids"),
        fields.get("citations"),
        fields.get("evidence_ids"),
    )
    run_ids = _safe_metadata_list(report_value("run_ids", "runIds", default=()))
    return SafeReportVersion(
        id=_text(report_value("id", default="")),
        status=_text(report_value("status", default="")),
        parent_id=_text(report_value("parent_id", "parentId", default="")),
        supersedes_id=_text(report_value("supersedes_id", "supersedesId", default="")),
        change_reason=_text(report_value("change_reason", "changeReason", default="")),
        references=references,
        withdrawn_claims=_safe_metadata_list(
            report_value("withdrawn_claims", "withdrawnClaims", default=()),
            metadata.get("withdrawn_claims"),
            metadata.get("withdrawnClaims"),
            fields.get("withdrawn_claims"),
            fields.get("withdrawnClaims"),
        ),
        run_ids=run_ids,
        sections=tuple(sections_by_id[index] for index in REPORT_SECTION_IDS if index in sections_by_id),
    )


def project_report_version(
    report: ReportVersion | Mapping[str, Any] | None,
) -> SafeReportVersion | None:
    """Project a domain report or safe mapping without copying private fields."""

    if report is None:
        return None
    return _project_report_version(report)


# Naming mirrors the frontend contract and keeps the backend adapter easy to
# discover for later composition work.
project_founder_graph_report_version = project_report_version


def _empty_section(section_id: int) -> SafeReportSection:
    return SafeReportSection(
        id=section_id,
        title=REPORT_SECTION_TITLES[section_id],
        present=False,
    )


def _section_signature(section: SafeReportSection) -> tuple[Any, ...]:
    return (
        section.present,
        section.content,
        section.facts,
        section.ai_inferences,
        section.unconfirmed,
        section.owner_decisions,
        section.claim_ids,
        section.evidence_ids,
        section.references,
        section.withdrawn_claims,
    )


@dataclass(frozen=True, slots=True)
class ReportSectionDiff:
    """One fixed chapter and its before/after safe projections."""

    id: int
    title: str
    status: str
    previous: SafeReportSection
    current: SafeReportSection

    @property
    def impacted(self) -> bool:
        return self.status != "unchanged"

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "previous": self.previous.as_dict(),
            "current": self.current.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class FounderGraphReportDiff:
    """Immutable result of comparing two report versions."""

    previous: SafeReportVersion | None
    current: SafeReportVersion | None
    sections: tuple[ReportSectionDiff, ...]
    follow_up_question: str = ""
    follow_up_evidence_ids: tuple[str, ...] = ()
    report_metadata_changed: bool = False

    @property
    def impacted_chapter_ids(self) -> tuple[int, ...]:
        return tuple(section.id for section in self.sections if section.impacted)

    @property
    def unchanged_chapter_ids(self) -> tuple[int, ...]:
        return tuple(section.id for section in self.sections if not section.impacted)

    @property
    def added_chapter_ids(self) -> tuple[int, ...]:
        return tuple(section.id for section in self.sections if section.status == "added")

    @property
    def changed_chapter_ids(self) -> tuple[int, ...]:
        return tuple(section.id for section in self.sections if section.status == "changed")

    @property
    def removed_chapter_ids(self) -> tuple[int, ...]:
        return tuple(section.id for section in self.sections if section.status == "removed")

    @property
    def references(self) -> tuple[str, ...]:
        """Return current report references, or previous references if absent."""

        report = self.current or self.previous
        return report.references if report is not None else ()

    @property
    def withdrawn_claims(self) -> tuple[str, ...]:
        report = self.current or self.previous
        return report.withdrawn_claims if report is not None else ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "previous": self.previous.as_dict() if self.previous else None,
            "current": self.current.as_dict() if self.current else None,
            "sections": [section.as_dict() for section in self.sections],
            "impacted_chapter_ids": list(self.impacted_chapter_ids),
            "unchanged_chapter_ids": list(self.unchanged_chapter_ids),
            "added_chapter_ids": list(self.added_chapter_ids),
            "changed_chapter_ids": list(self.changed_chapter_ids),
            "removed_chapter_ids": list(self.removed_chapter_ids),
            "follow_up_question": self.follow_up_question,
            "follow_up_evidence_ids": list(self.follow_up_evidence_ids),
            "references": list(self.references),
            "withdrawn_claims": list(self.withdrawn_claims),
            "report_metadata_changed": self.report_metadata_changed,
        }


ReportImpact = FounderGraphReportDiff


def _same_owner(previous: Any, current: Any) -> None:
    previous_owner = _field(previous, "owner_id", "ownerId", default=_MISSING) if previous is not None else _MISSING
    current_owner = _field(current, "owner_id", "ownerId", default=_MISSING) if current is not None else _MISSING
    if previous_owner is not _MISSING and current_owner is not _MISSING:
        previous_owner_text = _text(previous_owner)
        current_owner_text = _text(current_owner)
        if previous_owner_text and current_owner_text and previous_owner_text != current_owner_text:
            raise ReportDiffInputError("report versions must belong to the same owner")


def diff_report_versions(
    previous_report: ReportVersion | Mapping[str, Any] | None,
    current_report: ReportVersion | Mapping[str, Any] | None,
    *,
    follow_up_question: str | None = None,
    follow_up_evidence_ids: Iterable[Any] = (),
) -> FounderGraphReportDiff:
    """Compare two versions and classify every fixed chapter.

    ``follow_up_question`` and ``follow_up_evidence_ids`` are context for the
    revision that produced ``current_report``.  Chapter impact is determined
    only from the immutable before/after projection; no language model is
    invoked to guess a chapter from an unstructured question.  Evidence IDs
    are retained as safe metadata for the later write-back step.
    """

    _same_owner(previous_report, current_report)
    previous = project_report_version(previous_report)
    current = project_report_version(current_report)
    previous_sections = previous.section_map if previous is not None else {}
    current_sections = current.section_map if current is not None else {}
    diffs: list[ReportSectionDiff] = []
    for chapter in FOUNDER_GRAPH_REPORT_CHAPTERS:
        section_id = int(chapter["id"])
        before = previous_sections.get(section_id, _empty_section(section_id))
        after = current_sections.get(section_id, _empty_section(section_id))
        if not before.present and after.present:
            status = "added"
        elif before.present and not after.present:
            status = "removed"
        elif _section_signature(before) == _section_signature(after):
            status = "unchanged"
        else:
            status = "changed"
        diffs.append(
            ReportSectionDiff(
                id=section_id,
                title=str(chapter["title"]),
                status=status,
                previous=before,
                current=after,
            )
        )

    normalized_question = _text(follow_up_question)
    normalized_evidence_ids = _safe_metadata_list(follow_up_evidence_ids)
    previous_meta = (
        previous.references,
        previous.withdrawn_claims,
        previous.run_ids,
        previous.status,
        previous.change_reason,
    ) if previous is not None else None
    current_meta = (
        current.references,
        current.withdrawn_claims,
        current.run_ids,
        current.status,
        current.change_reason,
    ) if current is not None else None
    return FounderGraphReportDiff(
        previous=previous,
        current=current,
        sections=tuple(diffs),
        follow_up_question=normalized_question,
        follow_up_evidence_ids=normalized_evidence_ids,
        report_metadata_changed=previous_meta != current_meta,
    )


def analyze_report_impact(
    previous_report: ReportVersion | Mapping[str, Any] | None,
    current_report: ReportVersion | Mapping[str, Any] | None,
    *,
    follow_up_question: str | None = None,
    follow_up_evidence_ids: Iterable[Any] = (),
) -> FounderGraphReportDiff:
    """Descriptive alias for callers that only need impact analysis."""

    return diff_report_versions(
        previous_report,
        current_report,
        follow_up_question=follow_up_question,
        follow_up_evidence_ids=follow_up_evidence_ids,
    )


diff_founder_graph_reports = diff_report_versions


__all__ = [
    "FOUNDER_GRAPH_REPORT_CHAPTERS",
    "REPORT_CHANGE_STATUSES",
    "FounderGraphReportDiff",
    "ReportDiffInputError",
    "ReportImpact",
    "ReportSectionDiff",
    "SafeReportSection",
    "SafeReportVersion",
    "analyze_report_impact",
    "diff_founder_graph_reports",
    "diff_report_versions",
    "project_founder_graph_report_version",
    "project_report_version",
]
