"""Offline schema v1 to v2 migration spike for Founder Graph.

This module does not write to Neo4j.  It turns a small, JSON-like v1 export
into a deterministic inventory and a migration preview.  The preview is
intentionally conservative: every missing field, duplicate identity, and
unresolved reference is reported instead of being silently guessed.

The spike is useful before the real migration exists because it makes the
lossy parts of the old representation visible and gives the later migration
an explicit rollback/parity checklist.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any, Iterable, Mapping


SPIKE_VERSION = "schema-v2-spike-1"
DEFAULT_OWNER_ID = "synthetic-owner"

# These are the stable objects defined by the data-model document.  A legacy
# research_material is deliberately converted into a Source anchor plus a
# SourceRevision rather than kept as a separate v2 object.
ANCHOR_TYPES = frozenset(
    {
        "owner_profile",
        "idea",
        "asset",
        "person",
        "organization",
        "source",
        "research_campaign",
        "decision",
        "experiment",
        "instruction_artifact",
        "facet",
    }
)
LEGACY_SOURCE_TYPES = frozenset({"research_material", "source"})
PASSTHROUGH_TYPES = frozenset(
    {
        "source_revision",
        "content_chunk",
        "claim",
        "evidence",
        "research_run",
        "report_version",
        "report_section",
        "audit_event",
        "attachment",
        "campaign_authorization_snapshot",
    }
)

REQUIRED_NODE_FIELDS: dict[str, tuple[str, ...]] = {
    "owner_profile": ("id", "owner_id"),
    "idea": ("id", "owner_id", "title"),
    "asset": ("id", "owner_id", "name"),
    "person": ("id", "owner_id", "name"),
    "organization": ("id", "owner_id", "name"),
    "source": ("id", "owner_id", "title"),
    "research_material": ("id", "owner_id", "title", "content", "kind"),
    "source_revision": ("id", "owner_id", "source_id", "revision", "content_hash"),
    "content_chunk": ("id", "owner_id", "source_revision_id", "ordinal", "text_hash"),
    "claim": ("id", "owner_id", "text", "confidence", "status"),
    "evidence": ("id", "owner_id", "material_id"),
    "research_campaign": ("id", "owner_id", "purpose"),
    "research_run": ("id", "owner_id", "campaign_id", "status"),
    "report_version": ("id", "owner_id", "campaign_id", "status"),
    "report_section": ("id", "owner_id", "report_version_id", "section_id"),
    "decision": ("id", "owner_id", "title"),
    "experiment": ("id", "owner_id", "title"),
    "instruction_artifact": ("id", "owner_id", "path"),
    "facet": ("id", "owner_id", "namespace", "normalized_value"),
}

REQUIRED_RELATION_FIELDS = ("owner_id", "source_id", "target_id", "relation")

ROLLBACK_ASSUMPTIONS = (
    "入力JSONは読み取り専用で保持し、変換処理は入力を書き換えない",
    "変換結果は同じ入力ハッシュと変換版を持つため、同じ入力から再生成できる",
    "本移行は一括書込みを行わず、Neo4jへの反映は別工程の一取引で実行する",
    "反映前に入力snapshot、変換結果、対応表を同じ世代で保存する",
    "反映失敗時は新しいNeo4j側の書込みを破棄し、旧データを削除しない",
)

PARITY_CHECKS = (
    "入力のowner_idごとの件数と変換後のowner_idごとの件数が一致する",
    "入力IDから変換後IDへの対応表に欠落や重複がない",
    "根拠を持つ関係は、変換後も根拠IDを一件以上たどれる",
    "旧データの本文hashとSourceRevisionまたはContentChunkのhashが一致する",
    "変換前後で削除済み・非公開の情報が外部向け投影へ混ざらない",
)


@dataclass(frozen=True, slots=True)
class MigrationFinding:
    """One migration issue that a human can inspect before write-back."""

    category: str
    severity: str
    location: str
    message: str
    legacy_id: str | None = None
    field: str | None = None


@dataclass(frozen=True, slots=True)
class MigrationPreview:
    """Deterministic, write-free representation of the migration result."""

    input_sha256: str
    input_schema_version: int
    output_schema_version: int
    converted: dict[str, tuple[dict[str, Any], ...]]
    legacy_to_v2: dict[str, tuple[str, ...]]
    findings: tuple[MigrationFinding, ...]
    counts: dict[str, int]
    rollback_assumptions: tuple[str, ...] = ROLLBACK_ASSUMPTIONS
    parity_checks: tuple[str, ...] = PARITY_CHECKS

    @property
    def blocking_findings(self) -> tuple[MigrationFinding, ...]:
        return tuple(item for item in self.findings if item.severity == "blocking")

    @property
    def is_ready_for_write(self) -> bool:
        return not self.blocking_findings

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["findings"] = [asdict(item) for item in self.findings]
        result["blocking_findings"] = [asdict(item) for item in self.blocking_findings]
        result["is_ready_for_write"] = self.is_ready_for_write
        return result


def _string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _node_type(item: Mapping[str, Any]) -> str | None:
    value = item.get("node_type", item.get("type"))
    return _string(value.lower() if isinstance(value, str) else value)


def _stable_anchor_key(item: Mapping[str, Any], node_type: str, by_id: Mapping[str, Mapping[str, Any]]) -> str:
    """Resolve a legacy row to the identity that should survive revision.

    Legacy exports sometimes put the stable identity in ``entity_id`` or
    ``stable_key``.  For old revision rows that only contain ``supersedes_id``
    we follow that chain.  If none is present, the old ID remains the
    temporary identity and the preview records the assumption through the
    missing ``stable_identity`` finding.
    """

    explicit = _string(item.get("stable_key")) or _string(item.get("entity_id"))
    if explicit:
        return f"{node_type}:{explicit}"
    current = _string(item.get("id")) or "missing-id"
    seen: set[str] = set()
    while current not in seen:
        seen.add(current)
        prior = by_id.get(current)
        if prior is None:
            break
        parent = _string(prior.get("supersedes_id"))
        if not parent:
            break
        current = parent
    return f"{node_type}:{current}"


def _revision_number(item: Mapping[str, Any]) -> int:
    value = item.get("revision", 1)
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return 0


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _input_hash(payload: Mapping[str, Any]) -> str:
    return sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _finding(
    findings: list[MigrationFinding],
    category: str,
    severity: str,
    location: str,
    message: str,
    *,
    legacy_id: str | None = None,
    field: str | None = None,
) -> None:
    findings.append(MigrationFinding(category, severity, location, message, legacy_id, field))


def _validate_required_fields(
    item: Mapping[str, Any], node_type: str | None, location: str, findings: list[MigrationFinding]
) -> None:
    if node_type is None:
        _finding(findings, "missing_fields", "blocking", location, "node_type is missing", field="node_type")
        return
    fields = REQUIRED_NODE_FIELDS.get(node_type)
    if fields is None:
        _finding(findings, "unsupported_type", "blocking", location, f"unsupported node type: {node_type}")
        return
    for field_name in fields:
        value = item.get(field_name)
        if value is None or (isinstance(value, str) and not value.strip()):
            _finding(
                findings,
                "missing_fields",
                "blocking",
                location,
                f"required field is missing: {field_name}",
                legacy_id=_string(item.get("id")),
                field=field_name,
            )


def _legacy_id(item: Mapping[str, Any]) -> str | None:
    return _string(item.get("id"))


def _v2_id(prefix: str, legacy_id: str, *, suffix: str = "") -> str:
    safe = sha256(legacy_id.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{safe}{suffix}"


def _convert_node(
    item: Mapping[str, Any],
    node_type: str,
    *,
    by_id: Mapping[str, Mapping[str, Any]],
    findings: list[MigrationFinding],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (anchors, revisions/source revisions) for one legacy row."""

    legacy_id = _legacy_id(item)
    if legacy_id is None:
        return [], []
    owner_id = _string(item.get("owner_id"))
    if owner_id is None:
        return [], []
    if node_type in LEGACY_SOURCE_TYPES:
        anchor_id = _v2_id("source", legacy_id)
        revision = _revision_number(item)
        revision_id = _v2_id("source_revision", legacy_id, suffix=f"_r{revision or 1}")
        content = item.get("content") if isinstance(item.get("content"), str) else ""
        content_hash = _string(item.get("content_hash")) or sha256(content.encode("utf-8")).hexdigest()
        anchor = {
            "id": anchor_id,
            "legacy_id": legacy_id,
            "owner_id": owner_id,
            "entity_type": "source",
            "current_revision_id": revision_id,
        }
        source_revision = {
            "id": revision_id,
            "legacy_id": legacy_id,
            "owner_id": owner_id,
            "source_id": anchor_id,
            "revision": max(revision, 1),
            "content_hash": content_hash,
            "locator": item.get("locator"),
            "egress_policy": item.get("egress_policy", "local_only"),
        }
        return [anchor], [source_revision]

    if node_type in ANCHOR_TYPES:
        anchor_key = _stable_anchor_key(item, node_type, by_id)
        anchor_id = _v2_id("anchor", anchor_key)
        revision = max(_revision_number(item), 1)
        revision_id = _v2_id("entity_revision", legacy_id, suffix=f"_r{revision}")
        anchor = {
            "id": anchor_id,
            "legacy_id": legacy_id,
            "owner_id": owner_id,
            "entity_type": node_type,
            "current_revision_id": revision_id,
        }
        revision_payload = {
            "id": revision_id,
            "legacy_id": legacy_id,
            "owner_id": owner_id,
            "entity_id": anchor_id,
            "entity_type": node_type,
            "revision": revision,
            "content_hash": sha256(_canonical_json(dict(item)).encode("utf-8")).hexdigest(),
            "public_payload": {
                key: value
                for key, value in item.items()
                if key not in {"contact", "private_notes", "content", "raw_content"}
            },
        }
        return [anchor], [revision_payload]

    if node_type in PASSTHROUGH_TYPES:
        passthrough = dict(item)
        passthrough["legacy_id"] = legacy_id
        passthrough.setdefault("owner_id", owner_id)
        return [], [passthrough]

    # _validate_required_fields has already emitted the unsupported-type issue.
    return [], []


def _convert_relation(
    item: Mapping[str, Any],
    index: int,
    *,
    node_by_id: Mapping[str, Mapping[str, Any]],
    findings: list[MigrationFinding],
) -> dict[str, Any] | None:
    source_id = _string(item.get("source_id"))
    target_id = _string(item.get("target_id"))
    relation = _string(item.get("relation"))
    legacy_id = _legacy_id(item) or f"relation-{index + 1}"
    location = f"relationships[{index}]"
    if source_id is None or source_id not in node_by_id:
        _finding(findings, "orphan_relations", "blocking", location, "source endpoint does not exist", legacy_id=legacy_id, field="source_id")
    if target_id is None or target_id not in node_by_id:
        _finding(findings, "orphan_relations", "blocking", location, "target endpoint does not exist", legacy_id=legacy_id, field="target_id")
    if relation is None:
        _finding(findings, "missing_fields", "blocking", location, "relation is missing", legacy_id=legacy_id, field="relation")
    if source_id is None or target_id is None or relation is None:
        return None
    source = node_by_id.get(source_id)
    target = node_by_id.get(target_id)
    if source is not None and target is not None:
        source_owner = _string(source.get("owner_id"))
        target_owner = _string(target.get("owner_id"))
        relation_owner = _string(item.get("owner_id"))
        if relation_owner is None:
            _finding(findings, "missing_fields", "blocking", location, "relationship owner_id is missing", legacy_id=legacy_id, field="owner_id")
        if relation_owner and (relation_owner != source_owner or relation_owner != target_owner):
            _finding(findings, "owner_boundary", "blocking", location, "relationship crosses owner boundary", legacy_id=legacy_id, field="owner_id")
    evidence_ids = item.get("evidence_ids", ())
    if isinstance(evidence_ids, str):
        evidence_ids = (evidence_ids,)
    if evidence_ids is None:
        evidence_ids = ()
    if not isinstance(evidence_ids, Iterable):
        _finding(findings, "missing_fields", "blocking", location, "evidence_ids must be a list", legacy_id=legacy_id, field="evidence_ids")
        evidence_ids = ()
    evidence_ids = tuple(str(value) for value in evidence_ids)
    status = str(item.get("status", "inferred"))
    if status in {"inferred", "confirmed"} and not evidence_ids:
        _finding(
            findings,
            "missing_evidence",
            "blocking",
            location,
            "inferred or confirmed relationship requires at least one evidence reference",
            legacy_id=legacy_id,
            field="evidence_ids",
        )
    for evidence_id in evidence_ids:
        evidence = node_by_id.get(evidence_id)
        if evidence is None or _node_type(evidence) != "evidence":
            _finding(findings, "orphan_relations", "blocking", location, f"evidence does not exist: {evidence_id}", legacy_id=legacy_id, field="evidence_ids")
    return {
        "id": _v2_id("assertion", legacy_id),
        "legacy_id": legacy_id,
        "owner_id": _string(item.get("owner_id")),
        "predicate": relation,
        "source_legacy_id": source_id,
        "target_legacy_id": target_id,
        "evidence_legacy_ids": evidence_ids,
        "status": status,
        "confidence": item.get("confidence"),
        "expires_at": item.get("expires_at"),
    }


def _validate_node_references(
    nodes: tuple[Mapping[str, Any], ...],
    node_by_id: Mapping[str, Mapping[str, Any]],
    findings: list[MigrationFinding],
) -> None:
    """Report parent references that were encoded as fields in schema v1."""

    reference_fields = {
        "source_revision": ("source_id",),
        "content_chunk": ("source_revision_id",),
        "evidence": ("material_id", "source_revision_id"),
        "research_run": ("campaign_id",),
        "report_version": ("campaign_id",),
        "report_section": ("report_version_id",),
        "campaign_authorization_snapshot": ("campaign_id",),
    }
    for index, item in enumerate(nodes):
        node_type = _node_type(item)
        for field_name in reference_fields.get(node_type or "", ()):
            reference = _string(item.get(field_name))
            if reference and reference not in node_by_id:
                _finding(
                    findings,
                    "orphan_references",
                    "blocking",
                    f"nodes[{index}]",
                    f"referenced record does not exist: {reference}",
                    legacy_id=_legacy_id(item),
                    field=field_name,
                )


def convert_schema_v1_payload(payload: Mapping[str, Any]) -> MigrationPreview:
    """Inspect and preview a v1 export without touching external state."""

    if not isinstance(payload, Mapping):
        raise TypeError("schema v1 payload must be a mapping")
    findings: list[MigrationFinding] = []
    version = payload.get("schema_version", 1)
    if version != 1:
        _finding(findings, "schema_version", "blocking", "payload", "input schema_version must be 1")
    raw_nodes = payload.get("nodes", ())
    raw_relationships = payload.get("relationships", ())
    if not isinstance(raw_nodes, list) or not isinstance(raw_relationships, list):
        raise TypeError("payload nodes and relationships must be lists")
    nodes = tuple(item for item in raw_nodes if isinstance(item, Mapping))
    for index, item in enumerate(raw_nodes):
        if not isinstance(item, Mapping):
            _finding(findings, "invalid_record", "blocking", f"nodes[{index}]", "node must be an object")
    relationships = tuple(item for item in raw_relationships if isinstance(item, Mapping))
    for index, item in enumerate(raw_relationships):
        if not isinstance(item, Mapping):
            _finding(findings, "invalid_record", "blocking", f"relationships[{index}]", "relationship must be an object")

    node_by_id: dict[str, Mapping[str, Any]] = {}
    duplicate_ids: set[str] = set()
    for index, item in enumerate(nodes):
        node_id = _legacy_id(item)
        if node_id is None:
            _finding(findings, "missing_fields", "blocking", f"nodes[{index}]", "required field is missing: id", field="id")
            continue
        if node_id in node_by_id:
            duplicate_ids.add(node_id)
            _finding(findings, "duplicate_anchors", "blocking", f"nodes[{index}]", "legacy ID appears more than once", legacy_id=node_id, field="id")
        else:
            node_by_id[node_id] = item
        _validate_required_fields(item, _node_type(item), f"nodes[{index}]", findings)
    _validate_node_references(nodes, node_by_id, findings)

    # Group rows before conversion so a duplicate stable identity is visible
    # even when the old IDs were different.
    anchor_groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for item in nodes:
        node_type = _node_type(item)
        if node_type in ANCHOR_TYPES:
            anchor_groups[_stable_anchor_key(item, node_type, node_by_id)].append(item)
    for anchor_key, group in sorted(anchor_groups.items()):
        revisions = [_revision_number(item) for item in group]
        if len(group) > 1 and len(set(revisions)) != len(revisions):
            _finding(findings, "duplicate_anchors", "blocking", f"anchor:{anchor_key}", "same anchor has duplicate revision numbers", legacy_id=_legacy_id(group[0]), field="revision")
        current_rows = [item for item in group if item.get("is_current") is True or item.get("current") is True]
        if len(current_rows) > 1:
            _finding(findings, "duplicate_anchors", "blocking", f"anchor:{anchor_key}", "same anchor has more than one current row", legacy_id=_legacy_id(group[0]), field="is_current")
        if len(group) > 1 and not any(_string(item.get("stable_key")) or _string(item.get("entity_id")) or _string(item.get("supersedes_id")) for item in group):
            _finding(findings, "stable_identity", "warning", f"anchor:{anchor_key}", "multiple legacy rows have no explicit identity or revision link", legacy_id=_legacy_id(group[0]))

    converted_anchor_by_id: dict[str, dict[str, Any]] = {}
    converted_anchor_revision_by_id: dict[str, int] = {}
    converted_revisions: list[dict[str, Any]] = []
    mapping: dict[str, list[str]] = defaultdict(list)
    for item in nodes:
        node_type = _node_type(item)
        if node_type is None:
            continue
        anchors, revisions = _convert_node(item, node_type, by_id=node_by_id, findings=findings)
        for anchor in anchors:
            anchor_id = str(anchor["id"])
            prior = converted_anchor_by_id.get(anchor_id)
            if prior is None:
                converted_anchor_by_id[anchor_id] = anchor
                converted_anchor_revision_by_id[anchor_id] = max(_revision_number(item), 1)
                continue
            # Multiple legacy rows can be revisions of one stable object.  A
            # v2 anchor is emitted once; duplicate revision numbers remain a
            # blocking finding from the inventory pass above.
            next_revision = max(_revision_number(item), 1)
            if next_revision > converted_anchor_revision_by_id[anchor_id]:
                converted_anchor_by_id[anchor_id] = anchor
                converted_anchor_revision_by_id[anchor_id] = next_revision
        converted_revisions.extend(revisions)
        legacy_id = _legacy_id(item)
        if legacy_id:
            mapping[legacy_id].extend([str(value["id"]) for value in anchors + revisions if value.get("id")])

    converted_assertions: list[dict[str, Any]] = []
    for index, item in enumerate(relationships):
        assertion = _convert_relation(item, index, node_by_id=node_by_id, findings=findings)
        if assertion is not None:
            converted_assertions.append(assertion)
            legacy_id = str(assertion["legacy_id"])
            mapping[legacy_id].append(str(assertion["id"]))

    converted = {
        "anchors": tuple(sorted(converted_anchor_by_id.values(), key=lambda value: str(value.get("id")))),
        "revisions": tuple(sorted(converted_revisions, key=lambda value: str(value.get("id")))),
        "assertions": tuple(sorted(converted_assertions, key=lambda value: str(value.get("id")))),
    }
    # Resolve assertion endpoints after all anchors have been collected.  The
    # legacy IDs remain in parallel so rollback and manual inspection can use
    # the original export without guessing.
    anchor_id_by_legacy: dict[str, str] = {}
    for anchor in converted["anchors"]:
        legacy_id = _string(anchor.get("legacy_id"))
        if legacy_id:
            anchor_id_by_legacy[legacy_id] = str(anchor["id"])
    for revision in converted["revisions"]:
        legacy_id = _string(revision.get("legacy_id"))
        entity_id = _string(revision.get("entity_id")) or _string(revision.get("source_id"))
        if legacy_id and entity_id:
            # entity_id is already the v2 anchor for EntityRevision and
            # SourceRevision conversion.  This also maps old revision IDs
            # that were never themselves anchors.
            anchor_id_by_legacy[legacy_id] = entity_id
    assertions_with_v2_endpoints: list[dict[str, Any]] = []
    for assertion in converted["assertions"]:
        value = dict(assertion)
        source_legacy_id = _string(value.get("source_legacy_id"))
        target_legacy_id = _string(value.get("target_legacy_id"))
        if source_legacy_id:
            value["source_id"] = anchor_id_by_legacy.get(source_legacy_id, source_legacy_id)
        if target_legacy_id:
            value["target_id"] = anchor_id_by_legacy.get(target_legacy_id, target_legacy_id)
        assertions_with_v2_endpoints.append(value)
    converted["assertions"] = tuple(assertions_with_v2_endpoints)
    counts = {
        "input_nodes": len(nodes),
        "input_relationships": len(relationships),
        "anchors": len(converted["anchors"]),
        "revisions": len(converted["revisions"]),
        "assertions": len(converted["assertions"]),
        "duplicate_legacy_ids": len(duplicate_ids),
        "missing_fields": sum(item.category == "missing_fields" for item in findings),
        "missing_evidence": sum(item.category == "missing_evidence" for item in findings),
        "duplicate_anchors": sum(item.category == "duplicate_anchors" for item in findings),
        "orphan_relations": sum(item.category == "orphan_relations" for item in findings),
        "orphan_references": sum(item.category == "orphan_references" for item in findings),
        "owner_boundary_violations": sum(item.category == "owner_boundary" for item in findings),
        "blocking_findings": sum(item.severity == "blocking" for item in findings),
    }
    return MigrationPreview(
        input_sha256=_input_hash(payload),
        input_schema_version=int(version) if isinstance(version, int) else 0,
        output_schema_version=2,
        converted=converted,
        legacy_to_v2={key: tuple(values) for key, values in sorted(mapping.items())},
        findings=tuple(findings),
        counts=counts,
    )


def build_schema_v1_spike_fixture() -> dict[str, Any]:
    """Return a deterministic, PII-free fixture with 20 messages and 10 cards."""

    owner_id = DEFAULT_OWNER_ID
    nodes: list[dict[str, Any]] = []
    for index in range(1, 21):
        nodes.append(
            {
                "id": f"conversation-{index:02d}",
                "node_type": "research_material",
                "owner_id": owner_id,
                "title": f"合成会話 {index:02d}",
                "content": f"合成の創業アイデア会話 {index:02d}。実在の人物や会社を表さない。",
                "kind": "conversation",
                "locator": f"synthetic://conversation/{index:02d}",
                "revision": 1,
                "egress_policy": "local_only",
            }
        )
    for index in range(1, 11):
        nodes.append(
            {
                "id": f"card-{index:02d}",
                "node_type": "person",
                "owner_id": owner_id,
                "name": f"合成人物 {index:02d}",
                "stable_key": f"synthetic-person-{index:02d}",
                "kind": "person",
                "contact": {"email": f"person-{index:02d}@synthetic.invalid"},
                "private_notes": "synthetic_demo",
                "egress_policy": "local_only",
                "revision": 1,
            }
        )
    nodes.extend(
        [
            {
                "id": "idea-01",
                "node_type": "idea",
                "owner_id": owner_id,
                "title": "合成の名刺活用サービス",
                "summary": "人とアイデアを結び、次の検証を考える",
                "stable_key": "synthetic-idea-01",
                "revision": 1,
                "status": "draft",
            },
            {
                "id": "evidence-01",
                "node_type": "evidence",
                "owner_id": owner_id,
                "material_id": "conversation-01",
                "excerpt": "合成の根拠",
                "source_revision_id": "conversation-01",
            },
        ]
    )
    relationships = [
        {
            "id": "relation-01",
            "owner_id": owner_id,
            "source_id": "card-01",
            "target_id": "idea-01",
            "relation": "CAN_CONTRIBUTE_TO",
            "status": "inferred",
            "confidence": 0.7,
            "evidence_ids": ["evidence-01"],
        },
        {
            "id": "relation-02",
            "owner_id": owner_id,
            "source_id": "idea-01",
            "target_id": "card-01",
            "relation": "REUSES",
            "status": "proposed",
            "confidence": 0.5,
            "evidence_ids": [],
        },
    ]
    return {
        "schema_version": 1,
        "dataset_id": "founder-graph-schema-v2-spike",
        "provenance": {"status": "synthetic_demo", "generated_on": "2026-09-22"},
        "owner_id": owner_id,
        "nodes": nodes,
        "relationships": relationships,
    }


__all__ = [
    "MigrationFinding",
    "MigrationPreview",
    "build_schema_v1_spike_fixture",
    "convert_schema_v1_payload",
]
