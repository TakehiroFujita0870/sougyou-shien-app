"""Strict persistence encoding for immutable Neo4j IdeaBrief versions.

This module deliberately exposes no save/read store API. Atomic persistence is
added by the later T-IBP-02 packet after these serialized values are proven.
"""

from __future__ import annotations

from datetime import datetime
import json
from typing import Any, Mapping

from .idea_brief import IdeaBriefSection, IdeaBriefValidationError, IdeaBriefVersion


_NODE_TYPE = "idea_brief_version"
_PAYLOAD_KEYS = frozenset({
    "owner_id", "idea_lineage_root_id", "based_on_idea_id", "sections",
    "research_run_ids", "id", "revision", "supersedes_id", "change_reason",
    "egress_policy", "created_at",
})
_RECORD_KEYS = frozenset({
    "id", "owner_id", "node_type", "revision", "idea_lineage_root_id",
    "supersedes_id", "payload_json",
})
_SECTION_KEYS = frozenset({
    "index", "content", "facts", "inferences", "unconfirmed",
    "owner_decisions", "claim_ids", "evidence_ids",
})
_SECTION_SEQUENCE_FIELDS = (
    "facts", "inferences", "unconfirmed", "owner_decisions", "claim_ids", "evidence_ids",
)


def _serialize_persisted_idea_brief(brief: IdeaBriefVersion) -> dict[str, Any]:
    """Return the exact Neo4j metadata and JSON payload for one typed Brief."""

    if not isinstance(brief, IdeaBriefVersion):
        raise IdeaBriefValidationError("an IdeaBriefVersion value is required")
    payload = {
        "owner_id": brief.owner_id,
        "idea_lineage_root_id": brief.idea_lineage_root_id,
        "based_on_idea_id": brief.based_on_idea_id,
        "sections": [
            {
                "index": section.index,
                "content": section.content,
                **{name: list(getattr(section, name)) for name in _SECTION_SEQUENCE_FIELDS},
            }
            for section in brief.sections
        ],
        "research_run_ids": list(brief.research_run_ids),
        "id": brief.id,
        "revision": brief.revision,
        "supersedes_id": brief.supersedes_id,
        "change_reason": brief.change_reason,
        "egress_policy": brief.egress_policy,
        "created_at": brief.created_at.isoformat(),
    }
    return {
        "id": brief.id,
        "owner_id": brief.owner_id,
        "node_type": _NODE_TYPE,
        "revision": brief.revision,
        "idea_lineage_root_id": brief.idea_lineage_root_id,
        "supersedes_id": brief.supersedes_id,
        "payload_json": json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
    }


def _decode_persisted_idea_brief(record: Mapping[str, Any], *, owner_id: str) -> IdeaBriefVersion:
    """Hydrate only a complete payload whose durable metadata agrees with it."""

    if not isinstance(record, Mapping) or set(record) != _RECORD_KEYS:
        raise IdeaBriefValidationError("persisted IdeaBrief record fields are invalid")
    if not isinstance(owner_id, str) or not owner_id.strip() or record["owner_id"] != owner_id:
        raise IdeaBriefValidationError("persisted IdeaBrief owner is invalid")
    if record["node_type"] != _NODE_TYPE:
        raise IdeaBriefValidationError("persisted IdeaBrief type is invalid")
    if type(record["revision"]) is not int or record["revision"] < 1:
        raise IdeaBriefValidationError("persisted IdeaBrief revision is invalid")
    raw_payload = record["payload_json"]
    if not isinstance(raw_payload, str):
        raise IdeaBriefValidationError("persisted IdeaBrief payload is invalid")
    try:
        payload = json.loads(raw_payload)
    except (TypeError, ValueError):
        raise IdeaBriefValidationError("persisted IdeaBrief payload is invalid") from None
    if not isinstance(payload, dict) or set(payload) != _PAYLOAD_KEYS:
        raise IdeaBriefValidationError("persisted IdeaBrief payload fields are invalid")

    for name in ("id", "owner_id", "idea_lineage_root_id", "based_on_idea_id", "change_reason", "egress_policy", "created_at"):
        if not isinstance(payload[name], str):
            raise IdeaBriefValidationError("persisted IdeaBrief payload value is invalid")
    if payload["owner_id"] != owner_id or payload["id"] != record["id"]:
        raise IdeaBriefValidationError("persisted IdeaBrief identity is invalid")
    if type(payload["revision"]) is not int or payload["revision"] != record["revision"]:
        raise IdeaBriefValidationError("persisted IdeaBrief revision does not match its record")
    if payload["idea_lineage_root_id"] != record["idea_lineage_root_id"]:
        raise IdeaBriefValidationError("persisted IdeaBrief lineage does not match its record")
    if payload["supersedes_id"] != record["supersedes_id"]:
        raise IdeaBriefValidationError("persisted IdeaBrief predecessor does not match its record")
    if payload["supersedes_id"] is not None and not isinstance(payload["supersedes_id"], str):
        raise IdeaBriefValidationError("persisted IdeaBrief predecessor is invalid")
    if payload["egress_policy"] not in ("local_only", "shareable"):
        raise IdeaBriefValidationError("persisted IdeaBrief egress policy is invalid")
    try:
        created_at = datetime.fromisoformat(payload["created_at"].replace("Z", "+00:00"))
    except ValueError:
        raise IdeaBriefValidationError("persisted IdeaBrief creation time is invalid") from None
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise IdeaBriefValidationError("persisted IdeaBrief creation time is invalid")

    raw_sections = payload["sections"]
    if not isinstance(raw_sections, list) or len(raw_sections) != 8:
        raise IdeaBriefValidationError("persisted IdeaBrief must contain exactly eight sections")
    sections: list[IdeaBriefSection] = []
    for expected_index, raw_section in enumerate(raw_sections):
        if not isinstance(raw_section, dict) or set(raw_section) != _SECTION_KEYS:
            raise IdeaBriefValidationError("persisted IdeaBrief section fields are invalid")
        if type(raw_section["index"]) is not int or raw_section["index"] != expected_index:
            raise IdeaBriefValidationError("persisted IdeaBrief section indexes are invalid")
        if not isinstance(raw_section["content"], str):
            raise IdeaBriefValidationError("persisted IdeaBrief section content is invalid")
        if any(
            not isinstance(raw_section[name], list)
            or any(not isinstance(item, str) for item in raw_section[name])
            for name in _SECTION_SEQUENCE_FIELDS
        ):
            raise IdeaBriefValidationError("persisted IdeaBrief section references are invalid")
        sections.append(IdeaBriefSection(
            index=raw_section["index"],
            content=raw_section["content"],
            **{name: tuple(raw_section[name]) for name in _SECTION_SEQUENCE_FIELDS},
        ))

    raw_run_ids = payload["research_run_ids"]
    if not isinstance(raw_run_ids, list) or any(not isinstance(item, str) for item in raw_run_ids):
        raise IdeaBriefValidationError("persisted IdeaBrief Run references are invalid")
    try:
        brief = IdeaBriefVersion(
            owner_id=payload["owner_id"],
            idea_lineage_root_id=payload["idea_lineage_root_id"],
            based_on_idea_id=payload["based_on_idea_id"],
            sections=tuple(sections),
            research_run_ids=tuple(raw_run_ids),
            id=payload["id"],
            revision=payload["revision"],
            supersedes_id=payload["supersedes_id"],
            change_reason=payload["change_reason"],
            egress_policy=payload["egress_policy"],
            created_at=created_at,
        )
    except (TypeError, ValueError):
        raise IdeaBriefValidationError("persisted IdeaBrief payload is invalid") from None

    canonical_record = _serialize_persisted_idea_brief(brief)
    if any(canonical_record[key] != record[key] for key in _RECORD_KEYS - {"payload_json"}):
        raise IdeaBriefValidationError("persisted IdeaBrief metadata would change during hydration")
    canonical_payload = json.loads(canonical_record["payload_json"])
    if any(canonical_payload[key] != payload[key] for key in _PAYLOAD_KEYS - {"created_at"}):
        raise IdeaBriefValidationError("persisted IdeaBrief values would change during hydration")
    return brief
