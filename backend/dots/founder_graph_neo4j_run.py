"""Fail-closed decoding for persisted ResearchRun values."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
import json
import math
from typing import Any, Mapping

from .founder_graph import (
    DomainValidationError,
    EgressPolicy,
    NodeType,
    Provenance,
    ProvenanceOrigin,
    ResearchRun,
    Status,
    TransportRetry,
)


_RECORD_KEYS = frozenset({"id", "owner_id", "node_type", "revision", "payload_json"})
_TIMESTAMP_PATHS = frozenset({
    ("started_at",),
    ("finished_at",),
    ("provenance", "occurred_at"),
    ("transport_retries", "attempted_at"),
})


class ResearchRunDecodeError(ValueError):
    """Persisted Run data is incomplete, inconsistent, or not canonical."""


def _required_text(value: Any) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ResearchRunDecodeError("persisted ResearchRun text is invalid")
    return value


def _timestamp(value: Any, *, nullable: bool = False) -> datetime | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or not value or value != value.strip():
        raise ResearchRunDecodeError("persisted ResearchRun timestamp is invalid")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ResearchRunDecodeError("persisted ResearchRun timestamp is invalid") from None
    if result.tzinfo is None or result.utcoffset() is None:
        raise ResearchRunDecodeError("persisted ResearchRun timestamp must include a timezone")
    return result.astimezone(timezone.utc)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ResearchRunDecodeError("persisted ResearchRun JSON has duplicate keys")
        result[key] = value
    return result


def _reject_constant(_value: str) -> Any:
    raise ResearchRunDecodeError("persisted ResearchRun JSON contains a non-finite number")


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _json_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise ResearchRunDecodeError("persisted ResearchRun contains a non-JSON value")


def _same_payload_value(raw: Any, normalized: Any, path: tuple[str, ...] = ()) -> bool:
    if path in _TIMESTAMP_PATHS:
        if raw is None or normalized is None:
            return raw is None and normalized is None
        try:
            return _timestamp(raw) == _timestamp(normalized)
        except ResearchRunDecodeError:
            return False
    if isinstance(normalized, dict):
        return (
            isinstance(raw, dict)
            and set(raw) == set(normalized)
            and all(_same_payload_value(raw[key], normalized[key], path + (key,)) for key in normalized)
        )
    if isinstance(normalized, list):
        return (
            isinstance(raw, list)
            and len(raw) == len(normalized)
            and all(_same_payload_value(left, right, path) for left, right in zip(raw, normalized))
        )
    return type(raw) is type(normalized) and raw == normalized


def _decode_provenance(value: Any) -> Provenance:
    provenance_fields = {field.name for field in fields(Provenance)}
    if not isinstance(value, dict) or set(value) != provenance_fields:
        raise ResearchRunDecodeError("persisted ResearchRun provenance fields are invalid")
    for name in ("actor", "operation", "idempotency_key"):
        _required_text(value[name])
    for name in ("target_id", "source_id", "model_snapshot", "prompt_version", "rule_version"):
        if value[name] is not None:
            _required_text(value[name])
    origin = value["origin"]
    if not isinstance(origin, str) or origin not in {item.value for item in ProvenanceOrigin}:
        raise ResearchRunDecodeError("persisted ResearchRun provenance origin is invalid")
    values = dict(value)
    values["occurred_at"] = _timestamp(value["occurred_at"])
    try:
        return Provenance(**values)
    except (DomainValidationError, TypeError, ValueError):
        raise ResearchRunDecodeError("persisted ResearchRun provenance is invalid") from None


def _decode_retries(value: Any) -> tuple[TransportRetry, ...]:
    if not isinstance(value, list):
        raise ResearchRunDecodeError("persisted ResearchRun transport_retries must be an array")
    retry_fields = {field.name for field in fields(TransportRetry)}
    retries: list[TransportRetry] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != retry_fields:
            raise ResearchRunDecodeError("persisted ResearchRun retry fields are invalid")
        if item["error"] is not None:
            _required_text(item["error"])
        try:
            retries.append(TransportRetry(
                attempted_at=_timestamp(item["attempted_at"]),
                error=item["error"],
            ))
        except (DomainValidationError, TypeError, ValueError):
            raise ResearchRunDecodeError("persisted ResearchRun retry is invalid") from None
    return tuple(retries)


def decode_persisted_research_run(
    record: Mapping[str, Any], *, owner_id: str, expected_id: str,
) -> ResearchRun:
    """Hydrate a complete owner-scoped Run projection without inventing values."""

    if not isinstance(record, Mapping) or set(record) != _RECORD_KEYS:
        raise ResearchRunDecodeError("persisted ResearchRun record fields are invalid")
    _required_text(owner_id)
    if type(expected_id) is not str or not expected_id:
        raise ResearchRunDecodeError("persisted ResearchRun expected identity is invalid")
    if (
        type(record["id"]) is not str
        or type(record["owner_id"]) is not str
        or record["id"] != expected_id
        or record["owner_id"] != owner_id
    ):
        raise ResearchRunDecodeError("persisted ResearchRun record identity is invalid")
    if type(record["node_type"]) is not str or record["node_type"] != NodeType.RESEARCH_RUN.value:
        raise ResearchRunDecodeError("persisted node is not a ResearchRun")
    if type(record["revision"]) is not int or record["revision"] != 0:
        raise ResearchRunDecodeError("persisted ResearchRun record revision is invalid")
    raw_payload = record["payload_json"]
    if not isinstance(raw_payload, str):
        raise ResearchRunDecodeError("persisted ResearchRun payload is invalid")
    try:
        payload = json.loads(
            raw_payload,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except ResearchRunDecodeError:
        raise
    except (TypeError, ValueError):
        raise ResearchRunDecodeError("persisted ResearchRun payload is invalid JSON") from None
    run_fields = {field.name for field in fields(ResearchRun)}
    if not isinstance(payload, dict) or set(payload) != run_fields:
        raise ResearchRunDecodeError("persisted ResearchRun payload fields are invalid")
    if (
        type(payload["id"]) is not str
        or type(payload["owner_id"]) is not str
        or payload["id"] != expected_id
        or payload["owner_id"] != owner_id
    ):
        raise ResearchRunDecodeError("persisted ResearchRun payload identity is invalid")
    _required_text(payload["campaign_id"])
    _required_text(payload["model_snapshot"])
    if payload["authorization_snapshot_id"] is not None:
        _required_text(payload["authorization_snapshot_id"])
    if payload["authorization_revision"] is not None and (
        type(payload["authorization_revision"]) is not int or payload["authorization_revision"] < 1
    ):
        raise ResearchRunDecodeError("persisted ResearchRun authorization revision is invalid")
    if payload["parent_run_id"] is not None:
        _required_text(payload["parent_run_id"])
    if payload["supersedes_id"] is not None:
        _required_text(payload["supersedes_id"])
    for name in ("sources", "evidence_ids", "failures"):
        if not isinstance(payload[name], list):
            raise ResearchRunDecodeError(f"persisted ResearchRun {name} must be an array")
        for item in payload[name]:
            _required_text(item)
    for name in ("input_snapshot", "results"):
        if not isinstance(payload[name], dict):
            raise ResearchRunDecodeError(f"persisted ResearchRun {name} must be an object")
    if not isinstance(payload["status"], str) or payload["status"] not in {item.value for item in Status}:
        raise ResearchRunDecodeError("persisted ResearchRun status is invalid")
    if not isinstance(payload["egress_policy"], str) or payload["egress_policy"] not in {
        item.value for item in EgressPolicy
    }:
        raise ResearchRunDecodeError("persisted ResearchRun egress policy is invalid")
    started_at = _timestamp(payload["started_at"], nullable=True)
    finished_at = _timestamp(payload["finished_at"], nullable=True)
    if started_at is not None and finished_at is not None and finished_at < started_at:
        raise ResearchRunDecodeError("persisted ResearchRun finish precedes its start")

    values = dict(payload)
    values["started_at"] = started_at
    values["finished_at"] = finished_at
    values["provenance"] = _decode_provenance(payload["provenance"])
    values["transport_retries"] = _decode_retries(payload["transport_retries"])
    try:
        run = ResearchRun(**values)
    except (DomainValidationError, TypeError, ValueError):
        raise ResearchRunDecodeError("persisted ResearchRun payload is invalid") from None
    if not _same_payload_value(payload, _json_value(run)):
        raise ResearchRunDecodeError("persisted ResearchRun values would change during hydration")
    return run


__all__ = ["ResearchRunDecodeError", "decode_persisted_research_run"]
