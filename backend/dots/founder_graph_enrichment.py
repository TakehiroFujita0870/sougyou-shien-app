"""Pure, local-only enrichment proposals for the Founder Graph.

The module consumes owner-scoped read projections, reapplies the static
shareable allowlist, and returns immutable candidates. The initial grouping is
deterministic; a future Luna adapter can use the same proposal shapes.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from math import isfinite
from types import MappingProxyType
from typing import Any, TypeAlias

from .founder_graph import NodeType, SHAREABLE_PROJECTION_ALLOWLIST
from .founder_graph_read import GraphReadPort, NodeView, SearchHit
from .model_catalog import DEFAULT_MODEL_CATALOG, LUNA_LOGICAL_KEY, ModelCatalog


class EnrichmentError(ValueError):
    """A caller supplied an invalid local enrichment input."""


class EnrichmentProjectionError(EnrichmentError):
    """A projection is not safe or cannot be normalized."""


class EnrichmentKind(StrEnum):
    NAME_RESOLUTION = "name_resolution"
    FACET = "facet"
    CLUSTER = "cluster"


class EnrichmentStatus(StrEnum):
    PROPOSED = "proposed"


_PRIVATE_FIELDS = frozenset({
    "contact", "details", "private_notes", "source_text", "input_snapshot",
    "scope", "allowed_categories", "external_sources", "trial_budget", "path",
    "owner_id", "provenance",
})
_DISPLAY_FIELDS = ("title", "name", "display_name", "text", "purpose")
_FACET_FIELDS = ("kind", "tags", "claim_type", "polarity")
_SOURCE_FIELDS = ("source_id", "source_ids", "source_revision_id", "sources")
_EVIDENCE_FIELDS = ("evidence_id", "evidence_ids")


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EnrichmentError(f"{name} must be a non-empty string")
    return value.strip()


def _ids(value: object, name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = (value,)
    if isinstance(value, Mapping) or not isinstance(value, Iterable):
        raise EnrichmentError(f"{name} must be a sequence of strings")
    result: list[str] = []
    for item in value:
        item = _text(item, name)
        if item not in result:
            result.append(item)
    return tuple(result)


def _merge_ids(*values: object, name: str) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        for item in _ids(value, name):
            if item not in result:
                result.append(item)
    return tuple(result)


def _freeze(value: Any, path: str = "value") -> Any:
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        if not isfinite(value):
            raise EnrichmentProjectionError(f"{path} must contain finite numbers")
        return value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise EnrichmentProjectionError(f"{path} must use string keys")
            result[key] = _freeze(item, f"{path}.{key}")
        return MappingProxyType(dict(sorted(result.items())))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item, f"{path}[{index}]") for index, item in enumerate(value))
    raise EnrichmentProjectionError(f"{path} must contain JSON-like values")


def _json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json(item) for item in value]
    return value


def _display(fields: Mapping[str, Any], node_id: str) -> str:
    for key in _DISPLAY_FIELDS:
        value = fields.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return node_id


def _values(fields: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = fields.get(key)
    if isinstance(value, str):
        value = (value,)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    return tuple(item.strip() for item in value if isinstance(item, str) and item.strip())


def _field_ids(fields: Mapping[str, Any], keys: Sequence[str]) -> tuple[str, ...]:
    result: list[str] = []
    for key in keys:
        for item in _values(fields, key):
            if item not in result:
                result.append(item)
    return tuple(result)


def _normalized(value: str) -> str:
    return " ".join(value.casefold().split())


@dataclass(frozen=True, slots=True, kw_only=True)
class SafeNodeProjection:
    """Immutable shareable projection accepted by the proposal builder."""

    id: str
    node_type: str | NodeType
    fields: Mapping[str, Any]
    evidence_ids: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        node_id = _text(self.id, "id")
        try:
            node_type = self.node_type if isinstance(self.node_type, NodeType) else NodeType(self.node_type)
        except (TypeError, ValueError) as error:
            raise EnrichmentProjectionError("node_type is not allowlisted") from error
        if not isinstance(self.fields, Mapping):
            raise EnrichmentProjectionError("fields must be a mapping")
        raw = dict(self.fields)
        policy = raw.get("egress_policy")
        if policy is not None and policy != "shareable":
            raise EnrichmentProjectionError("only shareable projections are accepted")
        safe = {
            key: _freeze(raw[key], f"fields.{key}")
            for key in SHAREABLE_PROJECTION_ALLOWLIST[node_type]
            if key in raw and key not in _PRIVATE_FIELDS
        }
        safe["id"] = node_id
        object.__setattr__(self, "id", node_id)
        object.__setattr__(self, "node_type", node_type.value)
        object.__setattr__(self, "fields", MappingProxyType(safe))
        object.__setattr__(self, "evidence_ids", _merge_ids(self.evidence_ids, _field_ids(safe, _EVIDENCE_FIELDS), name="evidence_ids"))
        object.__setattr__(self, "source_ids", _merge_ids(self.source_ids, _field_ids(safe, _SOURCE_FIELDS), name="source_ids"))

    @property
    def title(self) -> str:
        return _display(self.fields, self.id)

    @classmethod
    def from_node_view(cls, view: NodeView, *, evidence_ids: Iterable[str] = (), source_ids: Iterable[str] = ()) -> "SafeNodeProjection":
        if not isinstance(view, NodeView):
            raise EnrichmentProjectionError("view must be a NodeView")
        fields = dict(view.fields)
        if fields.get("egress_policy") != "shareable":
            raise EnrichmentProjectionError("only shareable NodeView values are accepted")
        return cls(id=view.id, node_type=view.node_type, fields=fields, evidence_ids=evidence_ids, source_ids=source_ids)

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.node_type, "title": self.title, "fields": _json(self.fields), "evidence_ids": list(self.evidence_ids), "source_ids": list(self.source_ids), "egress_policy": "shareable"}


def _metadata(instance: Any) -> None:
    object.__setattr__(instance, "model_snapshot", _text(instance.model_snapshot, "model_snapshot"))
    object.__setattr__(instance, "evidence_ids", _ids(instance.evidence_ids, "evidence_ids"))
    object.__setattr__(instance, "source_ids", _ids(instance.source_ids, "source_ids"))
    if isinstance(instance.confidence, bool):
        raise EnrichmentError("confidence must be a number between 0 and 1")
    try:
        confidence = float(instance.confidence)
    except (TypeError, ValueError) as error:
        raise EnrichmentError("confidence must be a number between 0 and 1") from error
    if not isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        raise EnrichmentError("confidence must be a number between 0 and 1")
    object.__setattr__(instance, "confidence", confidence)
    try:
        status = instance.status if isinstance(instance.status, EnrichmentStatus) else EnrichmentStatus(instance.status)
    except (TypeError, ValueError) as error:
        raise EnrichmentError("status must be proposed") from error
    if status is not EnrichmentStatus.PROPOSED:
        raise EnrichmentError("status must be proposed")
    object.__setattr__(instance, "status", status)


@dataclass(frozen=True, slots=True, kw_only=True)
class _ProposalBase:
    model_snapshot: str
    confidence: float
    evidence_ids: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()
    status: str | EnrichmentStatus = EnrichmentStatus.PROPOSED

    def _common(self) -> dict[str, Any]:
        return {"model_snapshot": self.model_snapshot, "evidence_ids": list(self.evidence_ids), "source_ids": list(self.source_ids), "confidence": self.confidence, "status": self.status.value}


@dataclass(frozen=True, slots=True, kw_only=True)
class NameResolutionProposal(_ProposalBase):
    target_id: str
    canonical_id: str
    canonical_name: str

    def __post_init__(self) -> None:
        target, canonical = _text(self.target_id, "target_id"), _text(self.canonical_id, "canonical_id")
        if target == canonical:
            raise EnrichmentError("target_id and canonical_id must differ")
        object.__setattr__(self, "target_id", target)
        object.__setattr__(self, "canonical_id", canonical)
        object.__setattr__(self, "canonical_name", _text(self.canonical_name, "canonical_name"))
        _metadata(self)

    @property
    def kind(self) -> EnrichmentKind:
        return EnrichmentKind.NAME_RESOLUTION

    @property
    def proposal_type(self) -> str:
        return self.kind.value

    @property
    def target_ids(self) -> tuple[str, ...]:
        return (self.target_id,)

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind.value, "target_id": self.target_id, "canonical_id": self.canonical_id, "canonical_name": self.canonical_name, **self._common()}


@dataclass(frozen=True, slots=True, kw_only=True)
class FacetProposal(_ProposalBase):
    target_id: str
    facet_key: str
    facet_value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "target_id", _text(self.target_id, "target_id"))
        object.__setattr__(self, "facet_key", _text(self.facet_key, "facet_key"))
        object.__setattr__(self, "facet_value", _text(self.facet_value, "facet_value"))
        _metadata(self)

    @property
    def kind(self) -> EnrichmentKind:
        return EnrichmentKind.FACET

    @property
    def proposal_type(self) -> str:
        return self.kind.value

    @property
    def target_ids(self) -> tuple[str, ...]:
        return (self.target_id,)

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind.value, "target_id": self.target_id, "facet_key": self.facet_key, "facet_value": self.facet_value, **self._common()}


@dataclass(frozen=True, slots=True, kw_only=True)
class ClusterProposal(_ProposalBase):
    cluster_id: str
    label: str
    member_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "cluster_id", _text(self.cluster_id, "cluster_id"))
        object.__setattr__(self, "label", _text(self.label, "label"))
        members = _ids(self.member_ids, "member_ids")
        if len(members) < 2:
            raise EnrichmentError("cluster proposals require at least two member_ids")
        object.__setattr__(self, "member_ids", members)
        _metadata(self)

    @property
    def kind(self) -> EnrichmentKind:
        return EnrichmentKind.CLUSTER

    @property
    def proposal_type(self) -> str:
        return self.kind.value

    @property
    def target_ids(self) -> tuple[str, ...]:
        return self.member_ids

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind.value, "cluster_id": self.cluster_id, "label": self.label, "member_ids": list(self.member_ids), **self._common()}


EnrichmentProposal: TypeAlias = NameResolutionProposal | FacetProposal | ClusterProposal
EnrichmentInput: TypeAlias = SearchHit | NodeView | SafeNodeProjection | Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class EnrichmentProposalBatch:
    proposals: tuple[EnrichmentProposal, ...]
    model_snapshot: str
    next_cursor: str | None = None
    omitted_count: int = 0
    query: str | None = None

    def __post_init__(self) -> None:
        proposals = tuple(self.proposals)
        if not all(isinstance(item, (NameResolutionProposal, FacetProposal, ClusterProposal)) for item in proposals):
            raise EnrichmentError("proposals must contain enrichment proposal values")
        model = _text(self.model_snapshot, "model_snapshot")
        if any(item.model_snapshot != model for item in proposals):
            raise EnrichmentError("proposal model_snapshot must match batch model_snapshot")
        if not isinstance(self.omitted_count, int) or isinstance(self.omitted_count, bool) or self.omitted_count < 0:
            raise EnrichmentError("omitted_count must be a non-negative integer")
        if self.next_cursor is not None:
            _text(self.next_cursor, "next_cursor")
        if self.query is not None:
            _text(self.query, "query")
        object.__setattr__(self, "proposals", proposals)
        object.__setattr__(self, "model_snapshot", model)

    def __iter__(self) -> Iterator[EnrichmentProposal]:
        return iter(self.proposals)

    def __len__(self) -> int:
        return len(self.proposals)

    def __getitem__(self, index: int) -> EnrichmentProposal:
        return self.proposals[index]

    @property
    def items(self) -> tuple[EnrichmentProposal, ...]:
        return self.proposals

    def as_dict(self) -> dict[str, Any]:
        return {"query": self.query, "model_snapshot": self.model_snapshot, "proposals": [item.as_dict() for item in self.proposals], "next_cursor": self.next_cursor, "omitted_count": self.omitted_count}


def _mapping_projection(value: Mapping[str, Any]) -> SafeNodeProjection:
    node_id, node_type = value.get("id"), value.get("node_type", value.get("kind"))
    fields = value.get("fields", value)
    if not isinstance(fields, Mapping):
        raise EnrichmentProjectionError("fields must be a mapping")
    fields = dict(fields)
    policy, sensitivity = fields.get("egress_policy", value.get("egress_policy")), value.get("sensitivity")
    if (policy is not None and policy != "shareable") or (sensitivity is not None and sensitivity != "shareable"):
        raise EnrichmentProjectionError("only shareable mappings are accepted")
    if policy is None and sensitivity is None:
        try:
            node_enum = node_type if isinstance(node_type, NodeType) else NodeType(node_type)
            allowed = set(SHAREABLE_PROJECTION_ALLOWLIST[node_enum])
        except (TypeError, ValueError, KeyError) as error:
            raise EnrichmentProjectionError("node_type is not allowlisted") from error
        if not set(fields).issubset(allowed):
            raise EnrichmentProjectionError("policy is required for a broad projection")
    return SafeNodeProjection(id=node_id, node_type=node_type, fields=fields, evidence_ids=value.get("evidence_ids", ()), source_ids=value.get("source_ids", ()))


def _coerce(value: EnrichmentInput) -> SafeNodeProjection:
    if isinstance(value, SafeNodeProjection):
        return value
    if isinstance(value, SearchHit):
        return SafeNodeProjection.from_node_view(value.node)
    if isinstance(value, NodeView):
        return SafeNodeProjection.from_node_view(value)
    if isinstance(value, Mapping):
        return _mapping_projection(value)
    raise EnrichmentProjectionError("input must be a SearchHit, NodeView, SafeNodeProjection, or mapping")


def _facet_values(projection: SafeNodeProjection) -> tuple[tuple[str, str], ...]:
    result: list[tuple[str, str]] = []
    for field in _FACET_FIELDS:
        key = "tag" if field == "tags" else field
        for value in _values(projection.fields, field):
            if (key, value) not in result:
                result.append((key, value))
    return tuple(result)


def _proposal_ids(group: Iterable[SafeNodeProjection], field: str) -> tuple[str, ...]:
    return _merge_ids(*(item.evidence_ids if field == "evidence" else item.source_ids for item in group), name=f"{field}_ids")


def _cluster_id(node_type: str, key: str, value: str) -> str:
    digest = sha256(f"{node_type}|{key}|{_normalized(value)}".encode("utf-8")).hexdigest()[:16]
    return f"cluster_{digest}"


def _proposals(projections: tuple[SafeNodeProjection, ...], *, model: str, evidence_ids: tuple[str, ...], source_ids: tuple[str, ...]) -> tuple[EnrichmentProposal, ...]:
    result: list[EnrichmentProposal] = []
    name_groups: dict[tuple[str, str], list[SafeNodeProjection]] = {}
    for item in projections:
        name_groups.setdefault((item.node_type, _normalized(item.title)), []).append(item)
    for group in name_groups.values():
        if len(group) < 2:
            continue
        canonical = min(group, key=lambda item: item.id)
        for candidate in sorted(group, key=lambda item: item.id):
            if candidate.id == canonical.id:
                continue
            result.append(NameResolutionProposal(target_id=candidate.id, canonical_id=canonical.id, canonical_name=canonical.title, model_snapshot=model, evidence_ids=_merge_ids(evidence_ids, canonical.evidence_ids, candidate.evidence_ids, name="evidence_ids"), source_ids=_merge_ids(source_ids, canonical.source_ids, candidate.source_ids, name="source_ids"), confidence=0.95))

    facet_groups: dict[tuple[str, str, str], list[SafeNodeProjection]] = {}
    for item in projections:
        for key, value in _facet_values(item):
            result.append(FacetProposal(target_id=item.id, facet_key=key, facet_value=value, model_snapshot=model, evidence_ids=_merge_ids(evidence_ids, item.evidence_ids, name="evidence_ids"), source_ids=_merge_ids(source_ids, item.source_ids, name="source_ids"), confidence=0.75 if key == "kind" else 0.70))
            facet_groups.setdefault((item.node_type, key, _normalized(value)), []).append(item)
    for (node_type, key, normalized_value), group in facet_groups.items():
        unique = {item.id: item for item in group}
        if len(unique) < 2:
            continue
        members = tuple(sorted(unique))
        member_values = tuple(unique[item_id] for item_id in members)
        label = next(value for item in member_values for facet_key, value in _facet_values(item) if facet_key == key and _normalized(value) == normalized_value)
        result.append(ClusterProposal(cluster_id=_cluster_id(node_type, key, label), label=f"{key}:{label}", member_ids=members, model_snapshot=model, evidence_ids=_merge_ids(evidence_ids, _proposal_ids(member_values, "evidence"), name="evidence_ids"), source_ids=_merge_ids(source_ids, _proposal_ids(member_values, "source"), name="source_ids"), confidence=0.72))
    order = {EnrichmentKind.NAME_RESOLUTION: 0, EnrichmentKind.FACET: 1, EnrichmentKind.CLUSTER: 2}
    return tuple(sorted(result, key=lambda item: (order[item.kind], item.target_ids, getattr(item, "facet_key", ""), getattr(item, "facet_value", ""), getattr(item, "cluster_id", ""))))


def _is_read_port(value: object) -> bool:
    return callable(getattr(value, "search", None)) and isinstance(getattr(value, "owner_id", None), str)


def build_enrichment_proposals(
    source: GraphReadPort | Iterable[EnrichmentInput] | EnrichmentInput,
    query: str | None = None,
    *,
    owner_id: str | None = None,
    limit: int = 50,
    timeout_ms: int = 1_000,
    logical_key: str = LUNA_LOGICAL_KEY,
    catalog: ModelCatalog | None = None,
    evidence_ids: Iterable[str] = (),
    source_ids: Iterable[str] = (),
) -> EnrichmentProposalBatch:
    """Build a bounded proposal page from one local search or safe inputs."""

    catalog = catalog or DEFAULT_MODEL_CATALOG
    if not isinstance(catalog, ModelCatalog):
        raise EnrichmentError("catalog must be a ModelCatalog")
    model = catalog.resolve(logical_key)
    base_evidence, base_source = _ids(evidence_ids, "evidence_ids"), _ids(source_ids, "source_ids")
    cursor: str | None = None
    normalized_query: str | None = None
    if _is_read_port(source):
        if query is None or owner_id is None:
            raise EnrichmentError("query and owner_id are required for GraphReadPort input")
        normalized_query, owner = _text(query, "query"), _text(owner_id, "owner_id")
        if len(normalized_query) > 512:
            raise EnrichmentError("query must be at most 512 characters")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
            raise EnrichmentError("limit must be between 1 and 50")
        if not isinstance(timeout_ms, int) or isinstance(timeout_ms, bool) or not 1 <= timeout_ms <= 30_000:
            raise EnrichmentError("timeout_ms must be between 1 and 30000")
        if source.owner_id != owner:
            raise EnrichmentError("owner_id does not match the local graph owner")
        page = source.search(normalized_query, owner_id=owner, limit=limit, timeout_ms=timeout_ms)
        raw_inputs: Iterable[EnrichmentInput] = page.hits
        cursor = page.next_cursor
    else:
        if query is not None:
            normalized_query = _text(query, "query")
            if len(normalized_query) > 512:
                raise EnrichmentError("query must be at most 512 characters")
        if isinstance(source, (SearchHit, NodeView, SafeNodeProjection, Mapping)):
            raw_inputs = (source,)
        else:
            try:
                iter(source)
            except TypeError as error:
                raise EnrichmentError("source must be a read port, projection, or iterable") from error
            raw_inputs = source

    projections: list[SafeNodeProjection] = []
    seen: set[str] = set()
    omitted = 0
    for raw in raw_inputs:
        try:
            projection = _coerce(raw)
        except EnrichmentProjectionError:
            omitted += 1
            continue
        if projection.id in seen:
            omitted += 1
            continue
        seen.add(projection.id)
        projections.append(projection)
    return EnrichmentProposalBatch(proposals=_proposals(tuple(projections), model=model.snapshot, evidence_ids=base_evidence, source_ids=base_source), model_snapshot=model.snapshot, next_cursor=cursor, omitted_count=omitted, query=normalized_query)


def build_enrichment_proposals_from_hits(hits: Iterable[EnrichmentInput], **kwargs: Any) -> EnrichmentProposalBatch:
    """Convenience wrapper for callers holding a search page already."""

    return build_enrichment_proposals(hits, **kwargs)


propose_enrichment = build_enrichment_proposals

__all__ = [
    "ClusterProposal", "EnrichmentError", "EnrichmentInput", "EnrichmentKind", "EnrichmentProposal",
    "EnrichmentProposalBatch", "EnrichmentProjectionError", "EnrichmentStatus", "FacetProposal",
    "NameResolutionProposal", "SafeNodeProjection", "build_enrichment_proposals",
    "build_enrichment_proposals_from_hits", "propose_enrichment",
]
