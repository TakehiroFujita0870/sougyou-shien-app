"""Resolve historical Idea references across archive/restore-only successors."""

from __future__ import annotations

from datetime import datetime
from dataclasses import fields
from typing import Any, Iterable, Mapping, Sequence

from .founder_graph import Asset, AssetKind, EgressPolicy, Idea, PersonAsset, Provenance, ProvenanceOrigin, Status


_NON_CURRENT_IDEA_STATUSES = frozenset({
    Status.ARCHIVED, Status.SUPERSEDED, Status.RETRACTED, Status.EXPIRED,
    Status.CANCELLED, Status.REVOKED, Status.FAILED,
})
_UNSET = object()


def lifecycle_reference_aliases(records: Iterable[Idea | Asset]) -> dict[str, str]:
    """Build lifecycle-only aliases from a bounded set of typed owner records.

    Each predecessor chain is indexed once. A branch, missing predecessor,
    revision gap, or ordinary content revision prevents aliasing rather than
    selecting a candidate based on input order.
    """

    grouped: dict[tuple[type, str | None], dict[str, Idea | Asset]] = {}
    duplicate_groups: set[tuple[type, str | None]] = set()
    for record in records:
        if not isinstance(record, (Idea, Asset)):
            continue
        group = (type(record), record.owner_id)
        by_id = grouped.setdefault(group, {})
        if record.id in by_id:
            duplicate_groups.add(group)
        else:
            by_id[record.id] = record

    aliases: dict[str, str] = {}
    for group, by_id in grouped.items():
        if group in duplicate_groups:
            continue
        children: dict[str, list[Idea | Asset]] = {}
        for record in by_id.values():
            if record.supersedes_id is not None:
                children.setdefault(record.supersedes_id, []).append(record)
        roots = (record for record in by_id.values() if record.supersedes_id is None)
        for root in roots:
            chain: list[Idea | Asset] = [root]
            current = root
            while True:
                successors = children.get(current.id, ())
                if not successors:
                    break
                if len(successors) != 1:
                    chain = []
                    break
                successor = successors[0]
                if successor.revision != current.revision + 1:
                    chain = []
                    break
                chain.append(successor)
                current = successor
            if not chain:
                continue
            suffix_start = len(chain) - 1
            for index in range(len(chain) - 2, -1, -1):
                previous, current = chain[index], chain[index + 1]
                if _lifecycle_only_edge(previous, current):
                    suffix_start = index
                else:
                    break
            suffix = chain[suffix_start:]
            if len(suffix) < 2:
                continue
            resolve = resolve_restored_idea_reference if isinstance(root, Idea) else resolve_restored_asset_reference
            current_tip = resolve(suffix[0].id, suffix)
            if current_tip is not None:
                aliases.update((record.id, current_tip.id) for record in suffix)
    return aliases


def _lifecycle_only_edge(previous: Idea | Asset, current: Idea | Asset) -> bool:
    provenance = current.provenance
    if isinstance(previous, Idea) and isinstance(current, Idea):
        return (
            provenance.operation in {"archive_idea", "restore_idea"}
            and current.title == previous.title
            and current.summary == previous.summary
            and current.description == previous.description
            and current.source_text == previous.source_text
            and current.tags == previous.tags
            and current.egress_policy is previous.egress_policy
            and provenance.source_id == previous.id
            and provenance.target_id == current.id
        )
    if isinstance(previous, Asset) and isinstance(current, Asset):
        return (
            provenance.operation in {"archive_asset", "restore_asset"}
            and type(current) is type(previous)
            and current.name == previous.name
            and current.description == previous.description
            and current.details == previous.details
            and current.kind is previous.kind
            and current.egress_policy is previous.egress_policy
            and provenance.source_id == previous.id
            and provenance.target_id == current.id
        )
    return False


def decode_asset_lifecycle_record(
    payload: Any,
    *,
    owner_id: str,
    expected_id: str,
    expected_revision: Any = None,
    expected_supersedes_id: Any = _UNSET,
    allow_legacy_initial_row: bool = False,
) -> Asset:
    """Hydrate an exact persisted Asset/Person payload for lifecycle checks."""

    if not isinstance(payload, Mapping):
        raise ValueError("persisted Asset payload is invalid")
    normalized_legacy_row = False
    if allow_legacy_initial_row:
        record_type = PersonAsset if payload.get("kind") == AssetKind.PERSON.value else Asset
        expected_fields = {field.name for field in fields(record_type)}
        legacy_fields = expected_fields - {"revision", "supersedes_id"}
        if set(payload) == legacy_fields:
            # Match the established Neo4j Asset reader: old initial rows omit
            # both lineage fields and store scalar revision 0 (or 1). They are
            # current revision 1 only when the scalar predecessor is absent.
            if type(expected_revision) is not int or expected_revision not in {0, 1}:
                raise ValueError("legacy Asset revision metadata is invalid")
            if expected_supersedes_id is not None:
                raise ValueError("legacy Asset predecessor metadata is invalid")
            payload = {**payload, "revision": 1, "supersedes_id": None}
            normalized_legacy_row = True
    person_record = payload.get("kind") == AssetKind.PERSON.value
    record_type = PersonAsset if person_record else Asset
    names = {field.name for field in fields(record_type)}
    if set(payload) != names:
        raise ValueError("persisted Asset payload fields are invalid")
    if payload.get("owner_id") != owner_id or payload.get("id") != expected_id:
        raise ValueError("persisted Asset identity is invalid")
    if type(payload.get("revision")) is not int or payload["revision"] < 1:
        raise ValueError("persisted Asset revision is invalid")
    if (
        expected_revision is not None
        and not (normalized_legacy_row and expected_revision in {0, 1})
        and payload["revision"] != expected_revision
    ):
        raise ValueError("persisted Asset revision does not match its record")
    if expected_supersedes_id is not _UNSET and payload["supersedes_id"] != expected_supersedes_id:
        raise ValueError("persisted Asset predecessor does not match its record")
    created_at = payload.get("created_at")
    if not isinstance(created_at, str):
        raise ValueError("persisted Asset timestamp is invalid")
    try:
        parsed_created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        raw_provenance = payload.get("provenance")
        provenance_names = {field.name for field in fields(Provenance)}
        if not isinstance(raw_provenance, Mapping) or set(raw_provenance) != provenance_names:
            raise ValueError("persisted Asset provenance is invalid")
        provenance_values = dict(raw_provenance)
        occurred_at = provenance_values.get("occurred_at")
        if not isinstance(occurred_at, str):
            raise ValueError("persisted Asset provenance is invalid")
        provenance_values["occurred_at"] = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
        provenance_values["origin"] = ProvenanceOrigin(provenance_values["origin"])
        provenance = Provenance(**provenance_values)
        values = dict(payload)
        values["created_at"] = parsed_created_at
        values["provenance"] = provenance
        values["status"] = Status(values["status"])
        values["egress_policy"] = EgressPolicy(values["egress_policy"])
        values["kind"] = AssetKind(values["kind"])
        values.pop("kind") if person_record else None
        record = record_type(**values)
    except (KeyError, TypeError, ValueError):
        raise ValueError("persisted Asset payload is invalid") from None
    return record


def resolve_restored_idea_reference(reference_id: str, chain: Sequence[Idea]) -> Idea | None:
    """Return the active tip only when ``reference_id`` crosses lifecycle-only successors.

    This is deliberately not a general revision alias: any content revision,
    malformed lineage, branch, owner change, or altered shareability/content
    permanently prevents old references from becoming current again.
    """

    if not isinstance(reference_id, str) or not reference_id or not chain:
        return None
    if any(not isinstance(item, Idea) for item in chain):
        return None
    if chain[0].revision < 0 or chain[-1].status in _NON_CURRENT_IDEA_STATUSES:
        return None
    if any(
        current.owner_id != chain[0].owner_id
        or current.revision != previous.revision + 1
        or current.supersedes_id != previous.id
        for previous, current in zip(chain, chain[1:])
    ):
        return None
    index = next((i for i, node in enumerate(chain) if node.id == reference_id), None)
    if index is None:
        return None
    for position, (previous, current) in enumerate(zip(chain[index:], chain[index + 1:]), start=index + 1):
        provenance = current.provenance
        operation = provenance.operation
        if (
            current.title != previous.title
            or current.summary != previous.summary
            or current.description != previous.description
            or current.source_text != previous.source_text
            or current.tags != previous.tags
            or current.egress_policy is not previous.egress_policy
            or provenance.source_id != previous.id
            or provenance.target_id != current.id
        ):
            return None
        if operation == "archive_idea":
            if previous.status in _NON_CURRENT_IDEA_STATUSES or current.status is not Status.ARCHIVED:
                return None
        elif operation == "restore_idea":
            if previous.status is not Status.ARCHIVED:
                return None
            expected = next((item.status for item in reversed(chain[:position - 1])
                             if item.status is not Status.ARCHIVED), None)
            if expected in _NON_CURRENT_IDEA_STATUSES or current.status is not expected:
                return None
        else:
            return None
    return chain[-1]


def resolve_restored_asset_reference(reference_id: str, chain: Sequence[Asset]) -> Asset | None:
    """Resolve Asset references only across content-identical archive/restore successors."""

    if not isinstance(reference_id, str) or not reference_id or not chain:
        return None
    if any(not isinstance(item, Asset) for item in chain):
        return None
    if chain[0].revision < 1 or chain[-1].status is not Status.ACTIVE:
        return None
    if any(
        type(current) is not type(chain[0])
        or current.owner_id != chain[0].owner_id
        or current.kind is not chain[0].kind
        or current.egress_policy is not chain[0].egress_policy
        or current.details != chain[0].details
        or current.revision != previous.revision + 1
        or current.supersedes_id != previous.id
        for previous, current in zip(chain, chain[1:])
    ):
        return None
    index = next((i for i, node in enumerate(chain) if node.id == reference_id), None)
    if index is None:
        return None
    for previous, current in zip(chain[index:], chain[index + 1:]):
        provenance = current.provenance
        if (
            current.name != previous.name
            or current.description != previous.description
            or current.details != previous.details
            or current.kind is not previous.kind
            or current.egress_policy is not previous.egress_policy
            or provenance.source_id != previous.id
            or provenance.target_id != current.id
        ):
            return None
        if provenance.operation == "archive_asset":
            if previous.status is not Status.ACTIVE or current.status is not Status.ARCHIVED:
                return None
        elif provenance.operation == "restore_asset":
            if previous.status is not Status.ARCHIVED or current.status is not Status.ACTIVE:
                return None
        else:
            return None
    return chain[-1]
