"""Strict hydration helpers for immutable persisted Idea values."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import datetime
import json
from typing import Any, Mapping

from .founder_graph import EgressPolicy, Idea, NodeType, Provenance, ProvenanceOrigin, Status


class IdeaDecodeError(ValueError):
    """Persisted Idea content cannot be trusted as a typed owner value."""


def _timestamp(value: Any, *, nullable: bool = False) -> datetime | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise IdeaDecodeError("persisted Idea timestamp is invalid")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise IdeaDecodeError("persisted Idea timestamp is invalid") from None
    if result.tzinfo is None or result.utcoffset() is None:
        raise IdeaDecodeError("persisted Idea timestamp is invalid")
    return result


def _stable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value") and isinstance(value.value, str):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _stable(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _stable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_stable(item) for item in value]
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise IdeaDecodeError("persisted Idea JSON contains duplicate keys")
        result[key] = value
    return result


def _reject_constant(_value: str) -> Any:
    raise IdeaDecodeError("persisted Idea JSON contains a non-finite value")


def decode_persisted_idea(record: Any, *, owner_id: str, expected_id: str | None = None) -> Idea:
    """Decode an exact Idea payload, refusing defaults and normalization."""
    if not isinstance(record, Mapping) or set(record) != {
        "id", "owner_id", "node_type", "revision", "payload_json",
    }:
        raise IdeaDecodeError("persisted Idea record fields are invalid")
    if record["owner_id"] != owner_id or record["node_type"] != NodeType.IDEA.value:
        raise IdeaDecodeError("persisted Idea owner or type is invalid")
    if not isinstance(record["id"], str) or (expected_id is not None and record["id"] != expected_id):
        raise IdeaDecodeError("persisted Idea identity is invalid")
    if type(record["revision"]) is not int or record["revision"] < 0:
        raise IdeaDecodeError("persisted Idea revision is invalid")
    raw = record["payload_json"]
    if not isinstance(raw, str):
        raise IdeaDecodeError("persisted Idea payload is invalid")
    try:
        payload = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (TypeError, ValueError):
        raise IdeaDecodeError("persisted Idea payload is invalid") from None
    idea_fields = {item.name for item in fields(Idea)}
    if not isinstance(payload, dict) or set(payload) != idea_fields:
        raise IdeaDecodeError("persisted Idea payload fields are invalid")
    for name in ("owner_id", "id", "title", "summary", "description", "source_text", "status", "egress_policy", "created_at"):
        if type(payload[name]) is not str:
            raise IdeaDecodeError("persisted Idea payload value is invalid")
    if payload["updated_at"] is not None and type(payload["updated_at"]) is not str:
        raise IdeaDecodeError("persisted Idea update time is invalid")
    if type(payload["revision"]) is not int:
        raise IdeaDecodeError("persisted Idea revision is invalid")
    if payload["supersedes_id"] is not None and type(payload["supersedes_id"]) is not str:
        raise IdeaDecodeError("persisted Idea predecessor is invalid")
    if not isinstance(payload["tags"], list) or any(type(item) is not str for item in payload["tags"]):
        raise IdeaDecodeError("persisted Idea tags are invalid")
    if payload["id"] != record["id"] or payload["owner_id"] != owner_id:
        raise IdeaDecodeError("persisted Idea identity does not match its record")
    if type(payload["revision"]) is not int or payload["revision"] != record["revision"]:
        raise IdeaDecodeError("persisted Idea revision does not match its record")
    raw_provenance = payload["provenance"]
    provenance_fields = {item.name for item in fields(Provenance)}
    if not isinstance(raw_provenance, Mapping) or set(raw_provenance) != provenance_fields:
        raise IdeaDecodeError("persisted Idea provenance is invalid")
    for name in ("actor", "operation", "origin", "occurred_at", "idempotency_key"):
        if type(raw_provenance[name]) is not str:
            raise IdeaDecodeError("persisted Idea provenance is invalid")
    for name in ("target_id", "source_id", "model_snapshot", "prompt_version", "rule_version"):
        if raw_provenance[name] is not None and type(raw_provenance[name]) is not str:
            raise IdeaDecodeError("persisted Idea provenance is invalid")
    provenance_values = dict(raw_provenance)
    provenance_values["occurred_at"] = _timestamp(raw_provenance["occurred_at"])
    try:
        provenance_values["origin"] = ProvenanceOrigin(provenance_values["origin"])
        provenance = Provenance(**provenance_values)
        idea = Idea(
            owner_id=payload["owner_id"], id=payload["id"], title=payload["title"],
            summary=payload["summary"], description=payload["description"],
            source_text=payload["source_text"], tags=tuple(payload["tags"]),
            status=Status(payload["status"]), egress_policy=EgressPolicy(payload["egress_policy"]),
            revision=payload["revision"], supersedes_id=payload["supersedes_id"],
            created_at=_timestamp(payload["created_at"]),
            updated_at=_timestamp(payload["updated_at"], nullable=True), provenance=provenance,
        )
    except (TypeError, ValueError):
        raise IdeaDecodeError("persisted Idea payload is invalid") from None
    canonical = {item.name: _stable(getattr(idea, item.name)) for item in fields(Idea)}
    if canonical != payload:
        raise IdeaDecodeError("persisted Idea values would change during hydration")
    return idea
