"""Shared, read-only contract primitives for Founder Graph adapters."""

from __future__ import annotations

from typing import Any, Mapping

from .founder_graph import NodeType


NON_CURRENT_STATUSES = frozenset({"retracted", "superseded", "expired", "cancelled", "revoked", "archived"})
FIELD_ALLOWLIST: dict[NodeType, tuple[str, ...]] = {
    NodeType.OWNER_PROFILE: ("display_name", "status", "egress_policy"),
    NodeType.IDEA: ("title", "summary", "description", "source_text", "tags", "status", "egress_policy", "revision", "supersedes_id"),
    NodeType.ASSET: ("name", "kind", "description", "status", "egress_policy"),
    NodeType.PERSON: ("name", "description", "contact", "private_notes", "status", "egress_policy"),
    NodeType.ORGANIZATION: ("name", "description", "status", "egress_policy"),
    NodeType.SOURCE: ("title", "kind", "locator", "current_revision_id", "revision", "status", "egress_policy"),
    NodeType.RESEARCH_MATERIAL: ("title", "kind", "content", "locator", "content_hash", "status", "egress_policy"),
    NodeType.SOURCE_REVISION: ("source_id", "revision", "supersedes_id", "content", "locator", "content_hash", "retrieved_at", "egress_policy", "status"),
    NodeType.CLAIM: ("text", "claim_type", "confidence", "evidence_ids", "status", "revision", "supersedes_id", "egress_policy"),
    NodeType.EVIDENCE: ("material_id", "claim_id", "source_revision_id", "excerpt", "locator", "polarity", "confidence", "content_hash", "status", "egress_policy"),
    NodeType.RESEARCH_CAMPAIGN: ("purpose", "scope", "questions", "target_idea_id", "allowed_categories", "external_sources", "trial_budget", "expires_at", "status", "authorized", "aggregate_revision", "egress_policy"),
    NodeType.RESEARCH_RUN: ("campaign_id", "input_snapshot", "model_snapshot", "sources", "evidence_ids", "results", "failures", "status", "authorization_revision", "parent_run_id", "supersedes_id", "egress_policy"),
    NodeType.REPORT_VERSION: ("sections", "parent_id", "supersedes_id", "change_reason", "financial_formulas", "decision_criteria", "run_ids", "evidence_ids", "status", "egress_policy"),
    NodeType.REPORT_SECTION: ("id", "content", "facts", "ai_inferences", "unconfirmed", "owner_decisions", "claim_ids", "evidence_ids", "egress_policy"),
    NodeType.DECISION: ("text", "claim_ids", "report_ids", "experiment_ids", "status", "egress_policy"),
    NodeType.EXPERIMENT: ("name", "success_criteria", "stop_criteria", "status", "egress_policy"),
    NodeType.INSTRUCTION_ARTIFACT: ("path", "scope", "content_hash", "status", "egress_policy"),
    NodeType.ENTITY_REVISION: (
        "entity_id", "entity_type", "revision", "payload_schema", "public_payload",
        "content_hash", "created_at", "provenance_id", "status", "egress_policy",
    ),
    NodeType.RELATION_ASSERTION: (
        "source_id", "target_id", "source_kind", "target_kind", "predicate",
        "assertion_family_id", "revision", "status", "basis", "confidence", "evidence_ids",
        "valid_from", "expires_at", "supersedes_id", "provenance_id",
        "based_on_brief_id", "based_on_brief_section_index", "egress_policy",
    ),
    NodeType.CONTENT_CHUNK: ("source_revision_id", "ordinal", "char_start", "char_end", "text_hash", "status", "egress_policy"),
    NodeType.FACET: ("namespace", "normalized_value", "status", "egress_policy"),
}


def tokens(value: str) -> tuple[str, ...]:
    """Normalize search words exactly as the in-memory and Neo4j readers do."""

    return tuple(token for token in value.casefold().replace("\n", " ").split() if token)


def row_value(row: Any, key: str, default: Any = None) -> Any:
    """Read a field from Neo4j records and the mapping-like test records."""

    if isinstance(row, Mapping):
        return row.get(key, default)
    getter = getattr(row, "get", None)
    if callable(getter):
        try:
            value = getter(key)
        except (KeyError, TypeError):
            return default
        return default if value is None else value
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def single_record(result: Any) -> Any | None:
    """Return one optional result row across Neo4j and simple test doubles."""

    single = getattr(result, "single", None)
    if callable(single):
        try:
            return single(strict=False)
        except TypeError:
            return single()
    try:
        return next(iter(result), None)
    except TypeError:
        return None


def result_rows(result: Any) -> tuple[Any, ...]:
    """Materialize a result once, including single-row-only test doubles."""

    if result is None:
        return ()
    try:
        return tuple(result)
    except TypeError:
        row = single_record(result)
        return () if row is None else (row,)
