"""Provider-independent domain contracts for the local Founder Graph.

The module deliberately contains no database, network, or model-provider code.
It provides immutable value objects and small state-transition helpers that can
be adapted by a persistence or MCP layer later.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, replace
from datetime import datetime, timedelta, timezone
from enum import IntEnum, StrEnum
from hashlib import sha256
import json
from math import isfinite
from types import MappingProxyType
from typing import Any, Mapping, Sequence, TypeVar
from uuid import uuid4


UTC = timezone.utc


class DomainValidationError(ValueError):
    """Raised when a Founder Graph value violates its domain contract."""


E = TypeVar("E", bound=StrEnum)


def utc_now() -> datetime:
    """Return an aware UTC timestamp suitable for domain event fields."""

    return datetime.now(UTC)


def new_id(prefix: str = "") -> str:
    """Create a portable identifier, optionally namespaced by a short prefix."""

    token = str(uuid4())
    return f"{prefix}_{token}" if prefix else token


generate_id = new_id
now_utc = utc_now


def _identifier(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DomainValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _text(value: str, field_name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise DomainValidationError(f"{field_name} must be a string")
    if not allow_empty and not value.strip():
        raise DomainValidationError(f"{field_name} must not be empty")
    return value


def _enum(value: E | str, enum_type: type[E], field_name: str) -> E:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        allowed = ", ".join(member.value for member in enum_type)
        raise DomainValidationError(f"{field_name} must be one of: {allowed}") from error


def _timestamp(value: datetime | None, field_name: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise DomainValidationError(f"{field_name} must be a datetime")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _required_timestamp(value: datetime | None, field_name: str) -> datetime:
    timestamp = _timestamp(value, field_name)
    if timestamp is None:
        raise DomainValidationError(f"{field_name} is required")
    return timestamp


def _confidence(value: float | int | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise DomainValidationError("confidence must be a number between 0 and 1")
    try:
        normalized = float(value)
    except (TypeError, ValueError) as error:
        raise DomainValidationError("confidence must be a number between 0 and 1") from error
    if not isfinite(normalized) or not 0.0 <= normalized <= 1.0:
        raise DomainValidationError("confidence must be a number between 0 and 1")
    return normalized


def _strings(values: Any, field_name: str) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        values = (values,)
    try:
        result = tuple(_identifier(value, field_name) for value in values)
    except TypeError as error:
        raise DomainValidationError(f"{field_name} must be a sequence of strings") from error
    return result


def _freeze(value: Any, path: str = "value") -> Any:
    """Recursively freeze strict JSON-like values.

    Datetimes, enums, sets, bytes, arbitrary objects, and non-string mapping
    keys are intentionally rejected instead of being coerced into a lossy
    representation.
    """

    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        if not isfinite(value):
            raise DomainValidationError(f"{path} must contain finite JSON-like numbers")
        return value
    if isinstance(value, Mapping):
        pairs: list[tuple[str, Any]] = []
        for key, item in value.items():
            if type(key) is not str:
                raise DomainValidationError(f"{path} must use string JSON-like keys")
            pairs.append((key, _freeze(item, f"{path}.{key}")))
        return MappingProxyType(dict(sorted(pairs)))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item, f"{path}[{index}]") for index, item in enumerate(value))
    raise DomainValidationError(f"{path} must contain only JSON-like values")


def _canonical_json_value(value: Any) -> Any:
    """Return a JSON-serializable copy of a frozen JSON-like value."""

    if isinstance(value, Mapping):
        return {str(key): _canonical_json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonical_json_value(item) for item in value]
    return value


def _json_content_hash(value: Any) -> str:
    canonical = json.dumps(
        _canonical_json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def _fresh_provenance(
    previous: "Provenance | None",
    *,
    operation: str,
    target_id: str | None = None,
    occurred_at: datetime | None = None,
    provenance: "Provenance | None" = None,
) -> "Provenance":
    """Return non-reused transition provenance with a fresh idempotency key."""

    if provenance is None:
        actor = previous.actor if previous is not None else "system"
        return Provenance(
            actor=actor,
            operation=operation,
            origin=previous.origin if previous else ProvenanceOrigin.MANUAL,
            target_id=target_id,
            source_id=previous.source_id if previous else None,
            model_snapshot=previous.model_snapshot if previous else None,
            prompt_version=previous.prompt_version if previous else None,
            rule_version=previous.rule_version if previous else None,
            occurred_at=occurred_at or utc_now(),
        )
    if previous is not None and (
        provenance == previous or provenance.idempotency_key == previous.idempotency_key
    ):
        raise DomainValidationError("transition provenance and idempotency_key must be fresh")
    if target_id is not None and provenance.target_id != target_id:
        if provenance.origin is ProvenanceOrigin.GENERATED:
            raise DomainValidationError("generated provenance target_id must match aggregate id")
        provenance = replace(provenance, target_id=target_id)
    return provenance


def _validate_provenance_target(provenance: "Provenance", aggregate_id: str) -> None:
    """Keep generated audit metadata bound to the aggregate it describes."""

    if provenance.origin is ProvenanceOrigin.GENERATED and provenance.target_id != aggregate_id:
        raise DomainValidationError("generated provenance target_id must match aggregate id")


def _validate_transition_time(
    transition_at: datetime,
    *,
    prior_approved_at: datetime | None,
    prior_provenance: "Provenance",
    operation: str,
) -> None:
    """Reject transitions that would move the aggregate audit trail backwards."""

    boundaries = tuple(
        boundary
        for boundary in (prior_approved_at, prior_provenance.occurred_at)
        if boundary is not None
    )
    if boundaries and transition_at < max(boundaries):
        raise DomainValidationError(f"{operation} at must not precede prior audit time")


class Status(StrEnum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    PENDING = "pending"
    APPROVED = "approved"
    ACTIVE = "active"
    RUNNING = "running"
    PARTIAL = "partial"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRACTED = "retracted"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    REVOKED = "revoked"
    ARCHIVED = "archived"


class ReportStatus(StrEnum):
    DRAFT = "draft"
    FINAL = "final"


# Specific aliases keep the domain vocabulary discoverable without creating
# incompatible duplicate enum types.
EntityStatus = Status
IdeaStatus = Status
AssetStatus = Status
CampaignStatus = Status
RunStatus = Status
ClaimStatus = Status


class AssetKind(StrEnum):
    KNOWLEDGE = "knowledge"
    PERSON = "person"
    EXPERIENCE = "experience"
    ARTIFACT = "artifact"
    DATA = "data"
    EQUIPMENT = "equipment"
    CHANNEL = "channel"
    ORGANIZATION = "organization"


class MaterialKind(StrEnum):
    CONVERSATION = "conversation"
    DOCUMENT = "document"
    WEB = "web"
    FILE = "file"
    NOTE = "note"
    OTHER = "other"


ResearchMaterialKind = MaterialKind


class EgressPolicy(StrEnum):
    LOCAL_ONLY = "local_only"
    SHAREABLE = "shareable"
    EXPLICIT = "explicit"


DataPolicy = EgressPolicy


class ProvenanceOrigin(StrEnum):
    MANUAL = "manual"
    IMPORT = "import"
    GENERATED = "generated"


ProvenanceKind = ProvenanceOrigin


class ClaimType(StrEnum):
    FACT = "fact"
    AI_INFERENCE = "ai_inference"
    UNCONFIRMED = "unconfirmed"
    OWNER_DECISION = "owner_decision"

    # Short aliases used by adapters and callers.
    INFERENCE = "ai_inference"
    DECISION = "owner_decision"


ClaimKind = ClaimType


class EvidencePolarity(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    NEUTRAL = "neutral"
    REFUTES = "contradicts"


class RelationshipStatus(StrEnum):
    PROPOSED = "proposed"
    INFERRED = "inferred"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"


RelationStatus = RelationshipStatus


class RelationType(StrEnum):
    OWNS = "OWNS"
    GOVERNED_BY = "GOVERNED_BY"
    USES_SKILL = "USES_SKILL"
    REUSES = "REUSES"
    ADDRESSES = "ADDRESSES"
    DERIVED_FROM = "DERIVED_FROM"
    EVALUATED_BY = "EVALUATED_BY"
    WORKS_AT = "WORKS_AT"
    HAS_CAPABILITY = "HAS_CAPABILITY"
    CAN_CONTRIBUTE_TO = "CAN_CONTRIBUTE_TO"
    INTRODUCED_BY = "INTRODUCED_BY"
    REQUIRES_CAPABILITY = "REQUIRES_CAPABILITY"
    CLASSIFIED_AS = "CLASSIFIED_AS"
    SERVES = "SERVES"
    COMPETES_WITH = "COMPETES_WITH"
    DEPENDS_ON = "DEPENDS_ON"
    MERGED_INTO = "MERGED_INTO"
    HAS_REVISION = "HAS_REVISION"
    SUPPORTED_BY = "SUPPORTED_BY"
    CONTRADICTED_BY = "CONTRADICTED_BY"
    HAS_RUN = "HAS_RUN"
    PRODUCED = "PRODUCED"
    SUPERSEDES = "SUPERSEDES"
    BASED_ON = "BASED_ON"


class RelationAssertionEdgeType(StrEnum):
    """Persistence-only structural edges owned by RelationAssertion writes."""

    ASSERTS_FROM = "ASSERTS_FROM"
    ASSERTS_TO = "ASSERTS_TO"
    EVIDENCED_BY = "EVIDENCED_BY"
    SUPERSEDES = "SUPERSEDES"


class EvidenceEdgeType(StrEnum):
    EVIDENCE_FROM = "EVIDENCE_FROM"


RelationshipType = RelationType


class NodeType(StrEnum):
    OWNER_PROFILE = "owner_profile"
    IDEA = "idea"
    ASSET = "asset"
    PERSON = "person"
    ORGANIZATION = "organization"
    SOURCE = "source"
    RESEARCH_MATERIAL = "research_material"
    SOURCE_REVISION = "source_revision"
    EVIDENCE = "evidence"
    CLAIM = "claim"
    RESEARCH_CAMPAIGN = "research_campaign"
    RESEARCH_RUN = "research_run"
    REPORT_VERSION = "report_version"
    REPORT_SECTION = "report_section"
    DECISION = "decision"
    EXPERIMENT = "experiment"
    INSTRUCTION_ARTIFACT = "instruction_artifact"
    ENTITY_REVISION = "entity_revision"
    RELATION_ASSERTION = "relation_assertion"
    CONTENT_CHUNK = "content_chunk"
    FACET = "facet"


_NODE_TYPE_ALIASES = {
    "campaign": NodeType.RESEARCH_CAMPAIGN,
    "run": NodeType.RESEARCH_RUN,
    "report": NodeType.REPORT_VERSION,
    "material": NodeType.RESEARCH_MATERIAL,
    "source": NodeType.SOURCE,
    "source_revision": NodeType.SOURCE_REVISION,
}


def _node_type(value: NodeType | str, field_name: str) -> NodeType:
    if isinstance(value, NodeType):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _NODE_TYPE_ALIASES:
            return _NODE_TYPE_ALIASES[normalized]
        try:
            return NodeType(normalized)
        except ValueError:
            pass
    allowed = ", ".join(item.value for item in NodeType)
    raise DomainValidationError(f"{field_name} must be one of: {allowed}")


_ALLOWED_RELATION_ENDPOINTS: dict[RelationType, frozenset[tuple[NodeType, NodeType]]] = {
    RelationType.OWNS: frozenset({
        (NodeType.OWNER_PROFILE, NodeType.IDEA),
        (NodeType.OWNER_PROFILE, NodeType.ASSET),
        (NodeType.OWNER_PROFILE, NodeType.PERSON),
        (NodeType.OWNER_PROFILE, NodeType.ORGANIZATION),
        (NodeType.OWNER_PROFILE, NodeType.FACET),
        (NodeType.OWNER_PROFILE, NodeType.SOURCE),
        (NodeType.OWNER_PROFILE, NodeType.RESEARCH_MATERIAL),
        (NodeType.OWNER_PROFILE, NodeType.RESEARCH_CAMPAIGN),
    }),
    RelationType.GOVERNED_BY: frozenset({(NodeType.OWNER_PROFILE, NodeType.INSTRUCTION_ARTIFACT)}),
    RelationType.USES_SKILL: frozenset({(NodeType.OWNER_PROFILE, NodeType.INSTRUCTION_ARTIFACT)}),
    RelationType.REUSES: frozenset({(NodeType.IDEA, NodeType.ASSET)}),
    RelationType.ADDRESSES: frozenset({(NodeType.IDEA, NodeType.CLAIM)}),
    RelationType.DERIVED_FROM: frozenset({
        (NodeType.IDEA, NodeType.IDEA),
        (NodeType.ENTITY_REVISION, NodeType.SOURCE_REVISION),
        (NodeType.ENTITY_REVISION, NodeType.CONTENT_CHUNK),
        (NodeType.EVIDENCE, NodeType.RESEARCH_MATERIAL),
        (NodeType.EVIDENCE, NodeType.SOURCE_REVISION),
        (NodeType.CLAIM, NodeType.CLAIM),
    }),
    RelationType.EVALUATED_BY: frozenset({(NodeType.IDEA, NodeType.RESEARCH_CAMPAIGN)}),
    RelationType.WORKS_AT: frozenset({(NodeType.PERSON, NodeType.ORGANIZATION)}),
    RelationType.HAS_CAPABILITY: frozenset({(NodeType.PERSON, NodeType.ASSET)}),
    RelationType.CAN_CONTRIBUTE_TO: frozenset({(NodeType.PERSON, NodeType.IDEA)}),
    RelationType.INTRODUCED_BY: frozenset({(NodeType.PERSON, NodeType.PERSON)}),
    RelationType.REQUIRES_CAPABILITY: frozenset({(NodeType.IDEA, NodeType.ASSET)}),
    RelationType.CLASSIFIED_AS: frozenset({
        (NodeType.IDEA, NodeType.FACET),
        (NodeType.ASSET, NodeType.FACET),
        (NodeType.PERSON, NodeType.FACET),
        (NodeType.ORGANIZATION, NodeType.FACET),
        (NodeType.SOURCE, NodeType.FACET),
        (NodeType.CLAIM, NodeType.FACET),
    }),
    RelationType.SERVES: frozenset({(NodeType.IDEA, NodeType.PERSON), (NodeType.IDEA, NodeType.ORGANIZATION)}),
    RelationType.COMPETES_WITH: frozenset({(NodeType.IDEA, NodeType.IDEA), (NodeType.IDEA, NodeType.ORGANIZATION)}),
    RelationType.DEPENDS_ON: frozenset({
        (NodeType.IDEA, NodeType.IDEA),
        (NodeType.IDEA, NodeType.ASSET),
        (NodeType.EXPERIMENT, NodeType.ASSET),
    }),
    RelationType.MERGED_INTO: frozenset({
        (NodeType.IDEA, NodeType.IDEA),
        (NodeType.ASSET, NodeType.ASSET),
        (NodeType.PERSON, NodeType.PERSON),
        (NodeType.ORGANIZATION, NodeType.ORGANIZATION),
    }),
    RelationType.HAS_REVISION: frozenset({
        (NodeType.SOURCE, NodeType.SOURCE_REVISION),
        (NodeType.OWNER_PROFILE, NodeType.ENTITY_REVISION),
        (NodeType.IDEA, NodeType.ENTITY_REVISION),
        (NodeType.ASSET, NodeType.ENTITY_REVISION),
        (NodeType.PERSON, NodeType.ENTITY_REVISION),
        (NodeType.ORGANIZATION, NodeType.ENTITY_REVISION),
        (NodeType.FACET, NodeType.ENTITY_REVISION),
    }),
    RelationType.SUPPORTED_BY: frozenset({(NodeType.CLAIM, NodeType.EVIDENCE)}),
    RelationType.CONTRADICTED_BY: frozenset({(NodeType.CLAIM, NodeType.EVIDENCE)}),
    RelationType.HAS_RUN: frozenset({(NodeType.RESEARCH_CAMPAIGN, NodeType.RESEARCH_RUN)}),
    RelationType.PRODUCED: frozenset({(NodeType.RESEARCH_RUN, NodeType.REPORT_VERSION)}),
    RelationType.SUPERSEDES: frozenset({
        (NodeType.IDEA, NodeType.IDEA),
        (NodeType.CLAIM, NodeType.CLAIM),
        (NodeType.REPORT_VERSION, NodeType.REPORT_VERSION),
        (NodeType.SOURCE_REVISION, NodeType.SOURCE_REVISION),
        (NodeType.RELATION_ASSERTION, NodeType.RELATION_ASSERTION),
        (NodeType.ENTITY_REVISION, NodeType.ENTITY_REVISION),
    }),
    RelationType.BASED_ON: frozenset({
        (NodeType.DECISION, NodeType.CLAIM),
        (NodeType.DECISION, NodeType.REPORT_VERSION),
        (NodeType.DECISION, NodeType.EXPERIMENT),
    }),
}


@dataclass(frozen=True, slots=True, kw_only=True)
class Provenance:
    """Audit metadata required for generated or imported domain values."""

    actor: str = "system"
    operation: str = "create"
    origin: ProvenanceOrigin = ProvenanceOrigin.MANUAL
    target_id: str | None = None
    source_id: str | None = None
    model_snapshot: str | None = None
    prompt_version: str | None = None
    rule_version: str | None = None
    occurred_at: datetime = field(default_factory=utc_now)
    idempotency_key: str = field(default_factory=lambda: new_id("idem"))

    def __post_init__(self) -> None:
        object.__setattr__(self, "actor", _identifier(self.actor, "actor"))
        object.__setattr__(self, "operation", _identifier(self.operation, "operation"))
        object.__setattr__(self, "origin", _enum(self.origin, ProvenanceOrigin, "origin"))
        object.__setattr__(self, "occurred_at", _required_timestamp(self.occurred_at, "occurred_at"))
        for field_name in ("target_id", "source_id", "model_snapshot", "prompt_version", "rule_version"):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, _identifier(value, field_name))
        object.__setattr__(self, "idempotency_key", _identifier(self.idempotency_key, "idempotency_key"))
        if self.origin is ProvenanceOrigin.GENERATED:
            if not self.target_id or not self.source_id or not self.model_snapshot or not (self.prompt_version or self.rule_version):
                raise DomainValidationError(
                    "generated provenance requires target_id, source_id, model_snapshot, and prompt_version or rule_version"
                )

    @property
    def model(self) -> str | None:
        return self.model_snapshot

    @property
    def version(self) -> str | None:
        return self.prompt_version or self.rule_version


@dataclass(frozen=True, slots=True, kw_only=True)
class CampaignAuthorizationSnapshot:
    """An active, owner-scoped external-egress authorization snapshot."""

    owner_id: str
    campaign_id: str
    revision: int
    allowed_field_categories: tuple[str, ...]
    scope_target_ids: tuple[str, ...]
    expires_at: datetime
    id: str = field(default_factory=lambda: new_id("authorization"))

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner_id", _identifier(self.owner_id, "owner_id"))
        object.__setattr__(self, "campaign_id", _identifier(self.campaign_id, "campaign_id"))
        object.__setattr__(self, "id", _identifier(self.id, "id"))
        if not isinstance(self.revision, int) or isinstance(self.revision, bool) or self.revision < 1:
            raise DomainValidationError("authorization revision must be positive")
        object.__setattr__(self, "allowed_field_categories", _strings(self.allowed_field_categories, "allowed_field_categories"))
        object.__setattr__(self, "scope_target_ids", _strings(self.scope_target_ids, "scope_target_ids"))
        object.__setattr__(self, "expires_at", _required_timestamp(self.expires_at, "expires_at"))

    def is_active(self, *, at: datetime | None = None) -> bool:
        now = _required_timestamp(at or utc_now(), "at")
        return now < self.expires_at

    def validate(self, *, owner_id: str, target_id: str, categories: tuple[str, ...], at: datetime | None = None) -> None:
        if owner_id != self.owner_id:
            raise DomainValidationError("authorization owner does not match projection owner")
        if target_id not in self.scope_target_ids:
            raise DomainValidationError("authorization scope does not include projection target")
        if not self.is_active(at=at):
            raise DomainValidationError("authorization snapshot is expired")
        if not all(self.allows_category(category) for category in categories):
            raise DomainValidationError("projection field category is not authorized")

    def allows_category(self, category: str) -> bool:
        allowed = set(self.allowed_field_categories)
        return (
            category in allowed
            or category.split(".")[-1] in allowed
            or category.split(".")[0] in allowed
            or "*" in allowed
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class Idea:
    title: str
    owner_id: str | None = None
    id: str = field(default_factory=lambda: new_id("idea"))
    summary: str = ""
    description: str = ""
    source_text: str = ""
    tags: tuple[str, ...] = ()
    status: Status = Status.DRAFT
    egress_policy: EgressPolicy = EgressPolicy.LOCAL_ONLY
    revision: int = 0
    supersedes_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime | None = None
    provenance: Provenance = field(default_factory=Provenance)

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner_id", _identifier(self.owner_id, "owner_id"))
        object.__setattr__(self, "id", _identifier(self.id, "id"))
        object.__setattr__(self, "title", _text(self.title, "title"))
        object.__setattr__(self, "summary", _text(self.summary, "summary", allow_empty=True))
        object.__setattr__(self, "description", _text(self.description, "description", allow_empty=True))
        object.__setattr__(self, "source_text", _text(self.source_text, "source_text", allow_empty=True))
        object.__setattr__(self, "tags", _strings(self.tags, "tags"))
        object.__setattr__(self, "status", _enum(self.status, Status, "status"))
        object.__setattr__(self, "egress_policy", _enum(self.egress_policy, EgressPolicy, "egress_policy"))
        if not isinstance(self.revision, int) or isinstance(self.revision, bool) or self.revision < 0:
            raise DomainValidationError("revision must be a non-negative integer")
        if self.supersedes_id is not None:
            object.__setattr__(self, "supersedes_id", _identifier(self.supersedes_id, "supersedes_id"))
        object.__setattr__(self, "created_at", _required_timestamp(self.created_at, "created_at"))
        object.__setattr__(self, "updated_at", _timestamp(self.updated_at, "updated_at"))
        if not isinstance(self.provenance, Provenance):
            raise DomainValidationError("provenance must be a Provenance")
        _validate_provenance_target(self.provenance, self.id)

    def revise(
        self,
        *,
        title: str | None = None,
        summary: str | None = None,
        description: str | None = None,
        source_text: str | None = None,
        provenance: Provenance | None = None,
    ) -> "Idea":
        """Return a new revision and leave this revision untouched."""

        new_id_value = new_id("idea")
        return replace(
            self,
            id=new_id_value,
            title=self.title if title is None else title,
            summary=self.summary if summary is None else summary,
            description=self.description if description is None else description,
            source_text=self.source_text if source_text is None else source_text,
            revision=self.revision + 1,
            supersedes_id=self.id,
            created_at=utc_now(),
            updated_at=None,
            provenance=_fresh_provenance(
                self.provenance,
                operation="revise",
                target_id=new_id_value,
                provenance=provenance,
            ),
        )

    @property
    def parent_id(self) -> str | None:
        return self.supersedes_id

    @property
    def node_type(self) -> NodeType:
        return NodeType.IDEA


@dataclass(frozen=True, slots=True, kw_only=True)
class Asset:
    name: str
    owner_id: str | None = None
    kind: AssetKind = AssetKind.KNOWLEDGE
    id: str = field(default_factory=lambda: new_id("asset"))
    description: str = ""
    details: Mapping[str, Any] = field(default_factory=dict)
    status: Status = Status.ACTIVE
    egress_policy: EgressPolicy = EgressPolicy.LOCAL_ONLY
    created_at: datetime = field(default_factory=utc_now)
    provenance: Provenance = field(default_factory=Provenance)

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner_id", _identifier(self.owner_id, "owner_id"))
        object.__setattr__(self, "id", _identifier(self.id, "id"))
        object.__setattr__(self, "name", _text(self.name, "name"))
        object.__setattr__(self, "kind", _enum(self.kind, AssetKind, "kind"))
        object.__setattr__(self, "description", _text(self.description, "description", allow_empty=True))
        object.__setattr__(self, "details", _freeze(self.details))
        object.__setattr__(self, "status", _enum(self.status, Status, "status"))
        object.__setattr__(self, "egress_policy", _enum(self.egress_policy, EgressPolicy, "egress_policy"))
        if self.details and self.egress_policy is not EgressPolicy.LOCAL_ONLY:
            raise DomainValidationError("asset details require local_only egress policy")
        object.__setattr__(self, "created_at", _required_timestamp(self.created_at, "created_at"))
        if not isinstance(self.provenance, Provenance):
            raise DomainValidationError("provenance must be a Provenance")
        _validate_provenance_target(self.provenance, self.id)

    @classmethod
    def knowledge(cls, *, owner_id: str, name: str, **kwargs: Any) -> "KnowledgeAsset":
        return KnowledgeAsset(owner_id=owner_id, name=name, **kwargs)

    @classmethod
    def person(cls, *, owner_id: str, name: str, **kwargs: Any) -> "PersonAsset":
        return PersonAsset(owner_id=owner_id, name=name, **kwargs)

    @property
    def node_type(self) -> NodeType:
        return NodeType.ASSET

    def egress_projection(
        self,
        *,
        authorization: CampaignAuthorizationSnapshot | None = None,
        authorization_snapshot: CampaignAuthorizationSnapshot | None = None,
        campaign: ResearchCampaign | None = None,
        authorization_registry: CampaignAuthorizationRegistry | None = None,
        registry: CampaignAuthorizationRegistry | None = None,
        current_context: CampaignAuthorizationRegistry | None = None,
        at: datetime | None = None,
    ) -> dict[str, object]:
        return project_shareable(
            self,
            authorization=authorization,
            authorization_snapshot=authorization_snapshot,
            campaign=campaign,
            authorization_registry=authorization_registry,
            registry=registry,
            current_context=current_context,
            at=at,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class KnowledgeAsset(Asset):
    kind: AssetKind = field(default=AssetKind.KNOWLEDGE, init=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class PersonAsset(Asset):
    kind: AssetKind = field(default=AssetKind.PERSON, init=False)
    contact: Mapping[str, str] = field(default_factory=dict)
    private_notes: str = ""

    def __post_init__(self) -> None:
        Asset.__post_init__(self)
        object.__setattr__(self, "contact", _freeze(self.contact))
        object.__setattr__(self, "private_notes", _text(self.private_notes, "private_notes", allow_empty=True))
        if (self.contact or self.private_notes) and self.egress_policy is not EgressPolicy.LOCAL_ONLY:
            raise DomainValidationError("person contact/private_notes require local_only egress policy")

    @property
    def node_type(self) -> NodeType:
        return NodeType.PERSON


Knowledge = KnowledgeAsset
Person = PersonAsset


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchMaterial:
    title: str
    owner_id: str | None = None
    id: str = field(default_factory=lambda: new_id("material"))
    content: str = ""
    kind: MaterialKind = MaterialKind.NOTE
    locator: str | None = None
    content_hash: str | None = None
    retrieved_at: datetime = field(default_factory=utc_now)
    egress_policy: EgressPolicy = EgressPolicy.LOCAL_ONLY
    status: Status = Status.ACTIVE
    provenance: Provenance = field(default_factory=Provenance)

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner_id", _identifier(self.owner_id, "owner_id"))
        object.__setattr__(self, "id", _identifier(self.id, "id"))
        object.__setattr__(self, "title", _text(self.title, "title"))
        object.__setattr__(self, "content", _text(self.content, "content", allow_empty=True))
        object.__setattr__(self, "kind", _enum(self.kind, MaterialKind, "kind"))
        if self.locator is not None:
            object.__setattr__(self, "locator", _identifier(self.locator, "locator"))
        digest = sha256(self.content.encode("utf-8")).hexdigest()
        content_hash = self.content_hash or digest
        content_hash = _identifier(content_hash, "content_hash")
        if content_hash.lower() != digest:
            raise DomainValidationError("content_hash must match content")
        object.__setattr__(self, "content_hash", content_hash.lower())
        object.__setattr__(self, "retrieved_at", _required_timestamp(self.retrieved_at, "retrieved_at"))
        object.__setattr__(self, "egress_policy", _enum(self.egress_policy, EgressPolicy, "egress_policy"))
        object.__setattr__(self, "status", _enum(self.status, Status, "status"))
        if not isinstance(self.provenance, Provenance):
            raise DomainValidationError("provenance must be a Provenance")
        _validate_provenance_target(self.provenance, self.id)

    @property
    def hash(self) -> str | None:
        return self.content_hash

    @property
    def source_id(self) -> str:
        return self.id

    @property
    def node_type(self) -> NodeType:
        return NodeType.RESEARCH_MATERIAL

    def egress_projection(
        self,
        *,
        authorization: CampaignAuthorizationSnapshot | None = None,
        authorization_snapshot: CampaignAuthorizationSnapshot | None = None,
        campaign: ResearchCampaign | None = None,
        authorization_registry: CampaignAuthorizationRegistry | None = None,
        registry: CampaignAuthorizationRegistry | None = None,
        current_context: CampaignAuthorizationRegistry | None = None,
        at: datetime | None = None,
    ) -> dict[str, object]:
        return project_shareable(
            self,
            authorization=authorization,
            authorization_snapshot=authorization_snapshot,
            campaign=campaign,
            authorization_registry=authorization_registry,
            registry=registry,
            current_context=current_context,
            at=at,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class Evidence:
    material_id: str | None = None
    owner_id: str | None = None
    id: str = field(default_factory=lambda: new_id("evidence"))
    claim_id: str | None = None
    source_revision_id: str | None = None
    excerpt: str = ""
    locator: str | None = None
    polarity: EvidencePolarity = EvidencePolarity.SUPPORTS
    confidence: float = 1.0
    content_hash: str | None = None
    content_chunk_id: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    status: Status = Status.ACTIVE
    egress_policy: EgressPolicy = EgressPolicy.LOCAL_ONLY
    provenance: Provenance = field(default_factory=Provenance)

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner_id", _identifier(self.owner_id, "owner_id"))
        object.__setattr__(self, "id", _identifier(self.id, "id"))
        if self.material_id is not None:
            object.__setattr__(self, "material_id", _identifier(self.material_id, "material_id"))
        if self.claim_id is not None:
            object.__setattr__(self, "claim_id", _identifier(self.claim_id, "claim_id"))
        if self.source_revision_id is not None:
            object.__setattr__(self, "source_revision_id", _identifier(self.source_revision_id, "source_revision_id"))
        if self.content_chunk_id is not None:
            object.__setattr__(self, "content_chunk_id", _identifier(self.content_chunk_id, "content_chunk_id"))
        if (self.char_start is None) != (self.char_end is None):
            raise DomainValidationError("evidence locator offsets must be supplied together")
        if self.char_start is not None and (
            not isinstance(self.char_start, int) or isinstance(self.char_start, bool)
            or not isinstance(self.char_end, int) or isinstance(self.char_end, bool)
            or self.char_start < 0 or self.char_end <= self.char_start
        ):
            raise DomainValidationError("evidence locator offsets are invalid")
        if self.claim_id is None and self.source_revision_id is None:
            raise DomainValidationError("evidence must link a claim or source revision")
        if self.content_chunk_id is None and self.material_id is None:
            raise DomainValidationError("evidence must link a legacy material or content chunk")
        if self.content_chunk_id is not None and (self.claim_id is None or self.source_revision_id is None):
            raise DomainValidationError("source-grounded evidence requires a claim and source revision")
        object.__setattr__(self, "excerpt", _text(self.excerpt, "excerpt", allow_empty=True))
        if self.locator is not None:
            object.__setattr__(self, "locator", _identifier(self.locator, "locator"))
        if self.content_chunk_id is not None:
            if self.material_id is not None or self.excerpt or self.char_start is None:
                raise DomainValidationError("source-grounded evidence cannot copy material or excerpt text")
            expected_locator = f"chars:{self.char_start}-{self.char_end}"
            if self.locator != expected_locator:
                raise DomainValidationError("source-grounded evidence locator must match its stored range")
            if self.content_hash is None or len(self.content_hash) != 64 or any(
                char not in "0123456789abcdefABCDEF" for char in self.content_hash
            ):
                raise DomainValidationError("source-grounded evidence requires a SHA-256 content hash")
        object.__setattr__(self, "polarity", _enum(self.polarity, EvidencePolarity, "polarity"))
        object.__setattr__(self, "confidence", _confidence(self.confidence))
        if self.content_hash is not None:
            content_hash = _identifier(self.content_hash, "content_hash").lower()
            digest = sha256(self.excerpt.encode("utf-8")).hexdigest()
            if self.content_chunk_id is None and content_hash != digest:
                raise DomainValidationError("content_hash must match content")
            object.__setattr__(self, "content_hash", content_hash)
        object.__setattr__(self, "status", _enum(self.status, Status, "status"))
        object.__setattr__(self, "egress_policy", _enum(self.egress_policy, EgressPolicy, "egress_policy"))
        if not isinstance(self.provenance, Provenance):
            raise DomainValidationError("provenance must be a Provenance")
        _validate_provenance_target(self.provenance, self.id)

    @property
    def source_id(self) -> str:
        return self.source_revision_id or self.material_id

    @property
    def node_type(self) -> NodeType:
        return NodeType.EVIDENCE


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchCampaign:
    purpose: str
    owner_id: str | None = None
    id: str = field(default_factory=lambda: new_id("campaign"))
    scope: Any = field(default_factory=dict)
    questions: tuple[str, ...] = ()
    target_idea_id: str | None = None
    allowed_categories: tuple[str, ...] = ()
    external_sources: tuple[str, ...] = ()
    trial_budget: int = 1
    expires_at: datetime | None = None
    status: Status = Status.PENDING_APPROVAL
    egress_policy: EgressPolicy = EgressPolicy.LOCAL_ONLY
    authorized: bool = False
    approved_at: datetime | None = None
    authorization_snapshot_id: str | None = None
    prior_authorization_snapshot_id: str | None = None
    authorization_revision: int = 0
    aggregate_revision: int = 0
    run_count: int = 0
    created_at: datetime = field(default_factory=utc_now)
    provenance: Provenance = field(default_factory=Provenance)
    _internal_transition: bool = field(default=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner_id", _identifier(self.owner_id, "owner_id"))
        object.__setattr__(self, "id", _identifier(self.id, "id"))
        object.__setattr__(self, "purpose", _text(self.purpose, "purpose"))
        object.__setattr__(self, "scope", _freeze(self.scope))
        object.__setattr__(self, "questions", _strings(self.questions, "questions"))
        if self.target_idea_id is not None:
            object.__setattr__(self, "target_idea_id", _identifier(self.target_idea_id, "target_idea_id"))
        object.__setattr__(self, "allowed_categories", _strings(self.allowed_categories, "allowed_categories"))
        object.__setattr__(self, "external_sources", _strings(self.external_sources, "external_sources"))
        if not isinstance(self.trial_budget, int) or isinstance(self.trial_budget, bool) or self.trial_budget < 1:
            raise DomainValidationError("trial_budget must be at least 1")
        if not isinstance(self.run_count, int) or isinstance(self.run_count, bool) or self.run_count < 0:
            raise DomainValidationError("run_count must be a non-negative integer")
        if self.run_count > self.trial_budget:
            raise DomainValidationError("run_count cannot exceed trial_budget")
        object.__setattr__(self, "expires_at", _timestamp(self.expires_at, "expires_at"))
        object.__setattr__(self, "status", _enum(self.status, Status, "status"))
        object.__setattr__(self, "egress_policy", _enum(self.egress_policy, EgressPolicy, "egress_policy"))
        if not self._internal_transition and (self.authorized or self.status is Status.APPROVED or self.approved_at is not None):
            raise DomainValidationError("campaign authorization is only possible through approve()")
        if not isinstance(self.authorization_revision, int) or self.authorization_revision < 0:
            raise DomainValidationError("authorization_revision must be non-negative")
        if not isinstance(self.aggregate_revision, int) or isinstance(self.aggregate_revision, bool) or self.aggregate_revision < 0:
            raise DomainValidationError("aggregate_revision must be a non-negative integer")
        if self.authorization_snapshot_id is not None:
            object.__setattr__(self, "authorization_snapshot_id", _identifier(self.authorization_snapshot_id, "authorization_snapshot_id"))
        if self.prior_authorization_snapshot_id is not None:
            object.__setattr__(self, "prior_authorization_snapshot_id", _identifier(self.prior_authorization_snapshot_id, "prior_authorization_snapshot_id"))
        object.__setattr__(self, "approved_at", _timestamp(self.approved_at, "approved_at"))
        if self.authorized and (self.approved_at is None or self.authorization_snapshot_id is None):
            raise DomainValidationError("authorized campaigns require approved_at and a snapshot")
        object.__setattr__(self, "created_at", _required_timestamp(self.created_at, "created_at"))
        if not isinstance(self.provenance, Provenance):
            raise DomainValidationError("provenance must be a Provenance")
        _validate_provenance_target(self.provenance, self.id)

    @property
    def idea_id(self) -> str | None:
        return self.target_idea_id

    @property
    def allowed_data_categories(self) -> tuple[str, ...]:
        return self.allowed_categories

    @property
    def node_type(self) -> NodeType:
        return NodeType.RESEARCH_CAMPAIGN

    @property
    def authorization_snapshot(self) -> CampaignAuthorizationSnapshot:
        if not self.authorized or not self.authorization_snapshot_id:
            raise DomainValidationError("campaign has no active authorization snapshot")
        target_ids = []
        if self.target_idea_id:
            target_ids.append(self.target_idea_id)
        if isinstance(self.scope, Mapping) and "target_ids" in self.scope:
            target_ids.extend(_strings(self.scope["target_ids"], "scope.target_ids"))
        if not target_ids:
            target_ids.append(self.id)
        if self.expires_at is None:
            raise DomainValidationError("authorized campaign requires expires_at")
        return CampaignAuthorizationSnapshot(
            id=self.authorization_snapshot_id,
            owner_id=self.owner_id,
            campaign_id=self.id,
            revision=self.authorization_revision,
            allowed_field_categories=self.allowed_categories,
            scope_target_ids=tuple(dict.fromkeys(target_ids)),
            expires_at=self.expires_at,
        )

    def _transition(self, **changes: Any) -> "ResearchCampaign":
        values = {item.name: getattr(self, item.name) for item in fields(self)}
        values.update(changes)
        values["_internal_transition"] = True
        result = type(self)(**values)
        object.__setattr__(result, "_internal_transition", False)
        return result

    def approve(self, *, approved_at: datetime | None = None, provenance: Provenance | None = None) -> "ResearchCampaign":
        if self.authorized:
            raise DomainValidationError("campaign is already authorized; change scope for a new approval revision")
        at = _required_timestamp(approved_at or utc_now(), "approved_at")
        transition_provenance = _fresh_provenance(
            self.provenance,
            operation="approve",
            target_id=self.id,
            occurred_at=at,
            provenance=provenance,
        )
        _validate_transition_time(
            at,
            prior_approved_at=self.approved_at,
            prior_provenance=self.provenance,
            operation="approve",
        )
        if self.expires_at is not None and at >= self.expires_at:
            raise DomainValidationError("cannot approve an expired campaign")
        if self.status in {Status.CANCELLED, Status.REVOKED}:
            raise DomainValidationError("cannot approve a cancelled campaign")
        return self._transition(
            status=Status.APPROVED,
            authorized=True,
            approved_at=at,
            expires_at=self.expires_at or at + timedelta(days=1),
            authorization_snapshot_id=self.authorization_snapshot_id or new_id("authorization"),
            authorization_revision=max(1, self.authorization_revision),
            aggregate_revision=self.aggregate_revision + 1,
            provenance=transition_provenance,
        )

    def change_scope(
        self,
        scope: Any,
        *,
        at: datetime | None = None,
        provenance: Provenance | None = None,
    ) -> "ResearchCampaign":
        """Return a changed scope that requires a fresh approval snapshot."""

        transition_at = _required_timestamp(at or utc_now(), "at")
        transition_provenance = _fresh_provenance(
            self.provenance,
            operation="scope_change",
            target_id=self.id,
            occurred_at=transition_at,
            provenance=provenance,
        )
        _validate_transition_time(
            transition_at,
            prior_approved_at=self.approved_at,
            prior_provenance=self.provenance,
            operation="scope change",
        )
        return self._transition(
            scope=scope,
            status=Status.PENDING_APPROVAL,
            authorized=False,
            approved_at=None,
            authorization_snapshot_id=new_id("authorization"),
            prior_authorization_snapshot_id=self.authorization_snapshot_id,
            authorization_revision=self.authorization_revision + 1,
            aggregate_revision=self.aggregate_revision + 1,
            provenance=transition_provenance,
        )

    def can_start_run(self, *, at: datetime | None = None) -> bool:
        now = _timestamp(at or utc_now(), "at")
        if not self.authorized or self.status not in {Status.APPROVED, Status.RUNNING, Status.PARTIAL, Status.FAILED}:
            return False
        if self.expires_at is not None and now >= self.expires_at:
            return False
        return self.run_count < self.trial_budget

    def register_run(self, *, at: datetime | None = None, provenance: Provenance | None = None) -> "ResearchCampaign":
        transition_at = _required_timestamp(at or utc_now(), "at")
        if not self.can_start_run(at=transition_at):
            raise DomainValidationError("campaign is not authorized for another run")
        transition_provenance = _fresh_provenance(
            self.provenance,
            operation="register_run",
            target_id=self.id,
            occurred_at=transition_at,
            provenance=provenance,
        )
        _validate_transition_time(
            transition_at,
            prior_approved_at=self.approved_at,
            prior_provenance=self.provenance,
            operation="register_run",
        )
        return self._transition(
            run_count=self.run_count + 1,
            status=Status.RUNNING,
            aggregate_revision=self.aggregate_revision + 1,
            provenance=transition_provenance,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CampaignAuthorizationRegistry:
    """Immutable authoritative history used at authorization boundaries.

    A caller-supplied campaign is a historical value and cannot establish its
    own authority.  The registry owns the complete aggregate history and
    resolves the unique highest aggregate state revision for a campaign id.
    This is an internal trusted context: external input must not construct or
    replace it.  GraphWriteService and persistence enforcement are deferred to
    a later scope.  A pending scope-change revision therefore revokes the
    previous approval until a newer approval is registered.
    """

    campaigns: tuple[ResearchCampaign, ...]

    def __post_init__(self) -> None:
        history = tuple(self.campaigns)
        if not history:
            raise DomainValidationError("authorization registry requires campaign history")
        if not all(isinstance(campaign, ResearchCampaign) for campaign in history):
            raise DomainValidationError("authorization registry history must contain ResearchCampaign values")
        state_revisions: dict[tuple[str, int], ResearchCampaign] = {}
        snapshots: dict[str, CampaignAuthorizationSnapshot] = {}
        for campaign in history:
            state_key = (campaign.id, campaign.aggregate_revision)
            prior_state = state_revisions.get(state_key)
            if prior_state is not None and campaign != prior_state:
                raise DomainValidationError("authoritative campaign state revision is ambiguous")
            state_revisions[state_key] = campaign
            if campaign.authorized:
                snapshot = campaign.authorization_snapshot
                prior_snapshot = snapshots.get(snapshot.id)
                if prior_snapshot is not None and snapshot != prior_snapshot:
                    raise DomainValidationError("authorization registry contains conflicting snapshot payloads")
                snapshots[snapshot.id] = snapshot
        object.__setattr__(self, "campaigns", history)

    @classmethod
    def from_campaign_history(cls, campaigns: Sequence[ResearchCampaign]) -> "CampaignAuthorizationRegistry":
        return cls(campaigns=tuple(campaigns))

    @classmethod
    def from_campaign(cls, campaign: ResearchCampaign) -> "CampaignAuthorizationRegistry":
        return cls(campaigns=(campaign,))

    def resolve_current(self, campaign_id: str) -> tuple[ResearchCampaign, CampaignAuthorizationSnapshot]:
        """Resolve the current aggregate and snapshot from authoritative history."""

        identifier = _identifier(campaign_id, "campaign_id")
        candidates = tuple(campaign for campaign in self.campaigns if campaign.id == identifier)
        if not candidates:
            raise DomainValidationError("campaign is not present in authoritative authorization registry")
        states: dict[int, ResearchCampaign] = {}
        for campaign in candidates:
            prior = states.get(campaign.aggregate_revision)
            if prior is not None and campaign != prior:
                raise DomainValidationError("authoritative campaign state revision is ambiguous")
            states[campaign.aggregate_revision] = campaign
        current = states[max(states)]
        if not current.authorized:
            raise DomainValidationError("campaign has no current authorization snapshot")
        current_candidates = tuple(
            campaign for campaign in candidates if campaign.aggregate_revision == current.aggregate_revision
        )
        if any(campaign != current for campaign in current_candidates):
            raise DomainValidationError("authoritative campaign current pointer is ambiguous")
        return current, current.authorization_snapshot

    def current_campaign(self, campaign_id: str) -> ResearchCampaign:
        return self.resolve_current(campaign_id)[0]

    def current_snapshot(self, campaign_id: str) -> CampaignAuthorizationSnapshot:
        return self.resolve_current(campaign_id)[1]


@dataclass(frozen=True, slots=True)
class TransportRetry:
    attempted_at: datetime = field(default_factory=utc_now)
    error: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "attempted_at", _required_timestamp(self.attempted_at, "attempted_at"))
        if self.error is not None:
            object.__setattr__(self, "error", _text(self.error, "error"))


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchRun:
    campaign_id: str
    owner_id: str | None = None
    input_snapshot: Mapping[str, Any]
    model_snapshot: str
    sources: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    results: Mapping[str, Any] = field(default_factory=dict)
    failures: tuple[str, ...] = ()
    status: Status = Status.PENDING
    egress_policy: EgressPolicy = EgressPolicy.LOCAL_ONLY
    id: str = field(default_factory=lambda: new_id("run"))
    authorization_snapshot_id: str | None = None
    authorization_revision: int | None = None
    parent_run_id: str | None = None
    supersedes_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    transport_retries: tuple[TransportRetry, ...] = ()
    provenance: Provenance = field(default_factory=Provenance)

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner_id", _identifier(self.owner_id, "owner_id"))
        object.__setattr__(self, "id", _identifier(self.id, "id"))
        object.__setattr__(self, "campaign_id", _identifier(self.campaign_id, "campaign_id"))
        if self.authorization_snapshot_id is not None:
            object.__setattr__(self, "authorization_snapshot_id", _identifier(self.authorization_snapshot_id, "authorization_snapshot_id"))
        if self.authorization_revision is not None and (not isinstance(self.authorization_revision, int) or self.authorization_revision < 1):
            raise DomainValidationError("authorization_revision must be positive")
        if self.parent_run_id is not None:
            object.__setattr__(self, "parent_run_id", _identifier(self.parent_run_id, "parent_run_id"))
        if self.supersedes_id is not None:
            object.__setattr__(self, "supersedes_id", _identifier(self.supersedes_id, "supersedes_id"))
        if not isinstance(self.input_snapshot, Mapping):
            raise DomainValidationError("input_snapshot must be a mapping")
        object.__setattr__(self, "input_snapshot", _freeze(self.input_snapshot))
        object.__setattr__(self, "model_snapshot", _text(self.model_snapshot, "model_snapshot"))
        object.__setattr__(self, "sources", _strings(self.sources, "sources"))
        object.__setattr__(self, "evidence_ids", _strings(self.evidence_ids, "evidence_ids"))
        if not isinstance(self.results, Mapping):
            raise DomainValidationError("results must be a mapping")
        object.__setattr__(self, "results", _freeze(self.results))
        object.__setattr__(self, "failures", _strings(self.failures, "failures"))
        object.__setattr__(self, "status", _enum(self.status, Status, "status"))
        object.__setattr__(self, "egress_policy", _enum(self.egress_policy, EgressPolicy, "egress_policy"))
        object.__setattr__(self, "started_at", _timestamp(self.started_at, "started_at"))
        object.__setattr__(self, "finished_at", _timestamp(self.finished_at, "finished_at"))
        if self.status is Status.RUNNING and self.started_at is None:
            raise DomainValidationError("running runs require started_at")
        if self.status in {Status.COMPLETED, Status.PARTIAL, Status.FAILED, Status.CANCELLED, Status.EXPIRED, Status.REVOKED} and self.finished_at is None:
            raise DomainValidationError("terminal runs require finished_at")
        if not isinstance(self.transport_retries, tuple):
            object.__setattr__(self, "transport_retries", tuple(self.transport_retries))
        if not all(isinstance(item, TransportRetry) for item in self.transport_retries):
            raise DomainValidationError("transport_retries must contain TransportRetry values")
        if not isinstance(self.provenance, Provenance):
            raise DomainValidationError("provenance must be a Provenance")
        _validate_provenance_target(self.provenance, self.id)

    @property
    def node_type(self) -> NodeType:
        return NodeType.RESEARCH_RUN

    def _ensure_open(self) -> None:
        if self.status in {Status.COMPLETED, Status.PARTIAL, Status.FAILED, Status.CANCELLED, Status.EXPIRED, Status.REVOKED}:
            raise DomainValidationError("terminal runs cannot transition or retry")

    @property
    def source_ids(self) -> tuple[str, ...]:
        return self.sources

    @property
    def parent_id(self) -> str | None:
        return self.parent_run_id or self.supersedes_id

    @property
    def evidence(self) -> tuple[str, ...]:
        return self.evidence_ids

    @property
    def errors(self) -> tuple[str, ...]:
        return self.failures

    @property
    def completed_at(self) -> datetime | None:
        return self.finished_at

    def retry_transport(self, *, error: str | None = None, attempted_at: datetime | None = None) -> "ResearchRun":
        """Record transport retry metadata without changing run identity or policy."""

        self._ensure_open()
        retry = TransportRetry(attempted_at=attempted_at or utc_now(), error=error)
        return replace(
            self,
            transport_retries=self.transport_retries + (retry,),
            provenance=_fresh_provenance(self.provenance, operation="transport_retry", target_id=self.id),
        )

    def complete(
        self,
        *,
        evidence_ids: tuple[str, ...] | list[str] | None = None,
        results: Mapping[str, Any] | None = None,
        finished_at: datetime | None = None,
        provenance: Provenance | None = None,
    ) -> "ResearchRun":
        self._ensure_open()
        return replace(
            self,
            status=Status.COMPLETED,
            evidence_ids=self.evidence_ids if evidence_ids is None else tuple(evidence_ids),
            results=self.results if results is None else results,
            finished_at=finished_at or utc_now(),
            provenance=_fresh_provenance(self.provenance, operation="complete_run", target_id=self.id, provenance=provenance),
        )

    def partial(self, *, failures: tuple[str, ...] | list[str], finished_at: datetime | None = None, provenance: Provenance | None = None) -> "ResearchRun":
        self._ensure_open()
        return replace(self, status=Status.PARTIAL, failures=tuple(failures), finished_at=finished_at or utc_now(), provenance=_fresh_provenance(self.provenance, operation="partial_run", target_id=self.id, provenance=provenance))

    def fail(self, error: str, *, finished_at: datetime | None = None, provenance: Provenance | None = None) -> "ResearchRun":
        self._ensure_open()
        return replace(self, status=Status.FAILED, failures=self.failures + (_text(error, "error"),), finished_at=finished_at or utc_now(), provenance=_fresh_provenance(self.provenance, operation="fail_run", target_id=self.id, provenance=provenance))

    def new_strategy_run(
        self,
        *,
        input_snapshot: Mapping[str, Any],
        model_snapshot: str | None = None,
        sources: tuple[str, ...] | list[str] | None = None,
        provenance: Provenance | None = None,
    ) -> "ResearchRun":
        """Create a distinct run when the research policy or input changes."""

        new_id_value = new_id("run")
        return ResearchRun(
            id=new_id_value,
            campaign_id=self.campaign_id,
            input_snapshot=input_snapshot,
            model_snapshot=model_snapshot or self.model_snapshot,
            sources=self.sources if sources is None else tuple(sources),
            owner_id=self.owner_id,
            authorization_snapshot_id=self.authorization_snapshot_id,
            authorization_revision=self.authorization_revision,
            parent_run_id=self.id,
            provenance=_fresh_provenance(self.provenance, operation="new_strategy_run", target_id=new_id_value, provenance=provenance),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class Claim:
    text: str
    claim_type: ClaimType = ClaimType.FACT
    owner_id: str | None = None
    id: str = field(default_factory=lambda: new_id("claim"))
    classification: ClaimType | None = None
    confidence: float = 0.0
    evidence_ids: tuple[str, ...] = ()
    status: Status = Status.ACTIVE
    egress_policy: EgressPolicy = EgressPolicy.LOCAL_ONLY
    revision: int = 0
    supersedes_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    provenance: Provenance = field(default_factory=Provenance)

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner_id", _identifier(self.owner_id, "owner_id"))
        object.__setattr__(self, "id", _identifier(self.id, "id"))
        object.__setattr__(self, "text", _text(self.text, "text"))
        claim_type = _enum(self.claim_type, ClaimType, "claim_type")
        if self.classification is not None:
            classification = _enum(self.classification, ClaimType, "classification")
            if claim_type is not ClaimType.FACT and claim_type is not classification:
                raise DomainValidationError("claim_type and classification must agree")
            claim_type = classification
        object.__setattr__(self, "claim_type", claim_type)
        object.__setattr__(self, "classification", claim_type)
        normalized_confidence = _confidence(self.confidence)
        if normalized_confidence is None:
            raise DomainValidationError("claim confidence is required")
        object.__setattr__(self, "confidence", normalized_confidence)
        object.__setattr__(self, "evidence_ids", _strings(self.evidence_ids, "evidence_ids"))
        object.__setattr__(self, "status", _enum(self.status, Status, "status"))
        object.__setattr__(self, "egress_policy", _enum(self.egress_policy, EgressPolicy, "egress_policy"))
        if not isinstance(self.revision, int) or isinstance(self.revision, bool) or self.revision < 0:
            raise DomainValidationError("revision must be a non-negative integer")
        if self.supersedes_id is not None:
            object.__setattr__(self, "supersedes_id", _identifier(self.supersedes_id, "supersedes_id"))
        object.__setattr__(self, "created_at", _required_timestamp(self.created_at, "created_at"))
        if not isinstance(self.provenance, Provenance):
            raise DomainValidationError("provenance must be a Provenance")
        _validate_provenance_target(self.provenance, self.id)

    @property
    def type(self) -> ClaimType:
        return self.claim_type

    @property
    def kind(self) -> ClaimType:
        return self.claim_type

    @property
    def node_type(self) -> NodeType:
        return NodeType.CLAIM

    def revise(self, *, text: str, provenance: Provenance | None = None) -> "Claim":
        new_id_value = new_id("claim")
        return replace(
            self,
            id=new_id_value,
            text=text,
            revision=self.revision + 1,
            supersedes_id=self.id,
            created_at=utc_now(),
            provenance=_fresh_provenance(self.provenance, operation="revise_claim", target_id=new_id_value, provenance=provenance),
        )

    def retract(self, *, provenance: Provenance | None = None) -> "Claim":
        return replace(self, status=Status.RETRACTED, provenance=_fresh_provenance(self.provenance, operation="retract_claim", target_id=self.id, provenance=provenance))

    @property
    def parent_id(self) -> str | None:
        return self.supersedes_id


@dataclass(frozen=True, slots=True, kw_only=True)
class Relationship:
    owner_id: str | None = None
    source_id: str
    relation: RelationType
    target_id: str
    source_kind: NodeType | str
    target_kind: NodeType | str
    source_owner_id: str
    target_owner_id: str
    status: RelationshipStatus = RelationshipStatus.PROPOSED
    confidence: float | None = None
    evidence_ids: tuple[str, ...] = ()
    expires_at: datetime | None = None
    provenance: Provenance = field(default_factory=Provenance)
    state: RelationshipStatus | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner_id", _identifier(self.owner_id, "owner_id"))
        object.__setattr__(self, "source_id", _identifier(self.source_id, "source_id"))
        object.__setattr__(self, "target_id", _identifier(self.target_id, "target_id"))
        object.__setattr__(self, "relation", _enum(self.relation, RelationType, "relation"))
        object.__setattr__(self, "source_kind", _node_type(self.source_kind, "source_kind"))
        object.__setattr__(self, "target_kind", _node_type(self.target_kind, "target_kind"))
        object.__setattr__(self, "source_owner_id", _identifier(self.source_owner_id, "source_owner_id"))
        object.__setattr__(self, "target_owner_id", _identifier(self.target_owner_id, "target_owner_id"))
        if self.source_owner_id != self.owner_id or self.target_owner_id != self.owner_id:
            raise DomainValidationError("relationship endpoints must have the same owner")
        status = _enum(self.status, RelationshipStatus, "status")
        if self.state is not None:
            state = _enum(self.state, RelationshipStatus, "state")
            if status is not state:
                raise DomainValidationError("status and state must agree")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "state", status)
        object.__setattr__(self, "confidence", _confidence(self.confidence))
        object.__setattr__(self, "evidence_ids", _strings(self.evidence_ids, "evidence_ids"))
        object.__setattr__(self, "expires_at", _timestamp(self.expires_at, "expires_at"))
        if (self.source_kind, self.target_kind) not in _ALLOWED_RELATION_ENDPOINTS[self.relation]:
            raise DomainValidationError("relationship endpoint kinds are not allowed")
        if self.relation in {RelationType.CAN_CONTRIBUTE_TO, RelationType.INTRODUCED_BY}:
            if status not in {RelationshipStatus.PROPOSED, RelationshipStatus.INFERRED}:
                raise DomainValidationError("network relations must be proposed or inferred")
            if not self.evidence_ids:
                raise DomainValidationError("network relations require evidence")
            if self.confidence is None:
                raise DomainValidationError("network relations require confidence")
            if self.expires_at is None:
                raise DomainValidationError("network relations require an expiration")
        if not isinstance(self.provenance, Provenance):
            raise DomainValidationError("provenance must be a Provenance")
        _validate_provenance_target(self.provenance, self.target_id)

    @property
    def type(self) -> RelationType:
        return self.relation

    @classmethod
    def from_entities(cls, *, source: Any, relation: RelationType | str, target: Any, **kwargs: Any) -> "Relationship":
        source_owner = _identifier(source.owner_id, "source.owner_id")
        target_owner = _identifier(target.owner_id, "target.owner_id")
        if source_owner != target_owner:
            raise DomainValidationError("relationship endpoints must have the same owner")
        return cls(
            owner_id=source_owner,
            source_id=source.id,
            source_kind=source.node_type,
            source_owner_id=source_owner,
            relation=relation,
            target_id=target.id,
            target_kind=target.node_type,
            target_owner_id=target_owner,
            **kwargs,
        )

    def is_active(self, *, at: datetime | None = None) -> bool:
        now = _timestamp(at or utc_now(), "at")
        if self.status in {RelationshipStatus.REJECTED, RelationshipStatus.SUPERSEDED, RelationshipStatus.EXPIRED}:
            return False
        return self.expires_at is None or now < self.expires_at


class ReportSectionId(IntEnum):
    EXECUTIVE_SUMMARY = 0
    BUSINESS_MODEL = 1
    CUSTOMER_AND_MARKET_SIZE = 2
    REVENUE_MODEL = 3
    COMPETITIVE_ADVANTAGE = 4
    FEASIBILITY = 5
    RISK_AND_EXIT_LINE = 6
    RISK_MINIMUM_ROADMAP = 7

    @property
    def title(self) -> str:
        return REPORT_SECTION_TITLES[int(self)]


ReportSectionID = ReportSectionId


REPORT_SECTION_TITLES: Mapping[int, str] = MappingProxyType(
    {
        0: "エグゼクティブサマリー",
        1: "ビジネスモデル",
        2: "顧客とマーケットサイズ",
        3: "収益モデル",
        4: "競争優位性",
        5: "実現可能性",
        6: "リスク・撤退ライン",
        7: "リスクミニマムなロードマップ",
    }
)
REPORT_SECTION_NAMES = REPORT_SECTION_TITLES
REPORT_SECTION_IDS = tuple(range(8))

# A final report is not complete merely because it has eight section-shaped
# values.  These keys are the stable minimum contract shared by report
# writers and readers; draft reports may omit both maps while being edited.
REQUIRED_FINANCIAL_FORMULA_KEYS = frozenset({"break_even"})
REQUIRED_DECISION_CRITERIA_KEYS = frozenset({"stop"})


def _validate_final_report_contract(
    financial_formulas: Any,
    decision_criteria: Any,
) -> None:
    """Validate the stable minimum maps required by a final report."""

    if not isinstance(financial_formulas, Mapping):
        raise DomainValidationError("final report financial_formulas must be a mapping")
    missing_formulas = REQUIRED_FINANCIAL_FORMULA_KEYS.difference(financial_formulas)
    if missing_formulas:
        missing = ", ".join(sorted(missing_formulas))
        raise DomainValidationError(f"final report financial_formulas requires keys: {missing}")
    if not isinstance(decision_criteria, Mapping):
        raise DomainValidationError("final report decision_criteria must be a mapping")
    missing_criteria = REQUIRED_DECISION_CRITERIA_KEYS.difference(decision_criteria)
    if missing_criteria:
        missing = ", ".join(sorted(missing_criteria))
        raise DomainValidationError(f"final report decision_criteria requires keys: {missing}")


def report_section_title(section_id: int | ReportSectionId) -> str:
    if isinstance(section_id, bool) or not isinstance(section_id, (int, ReportSectionId)):
        raise DomainValidationError("report section id must be an integer from 0 to 7")
    try:
        return REPORT_SECTION_TITLES[section_id]
    except (KeyError, TypeError, ValueError) as error:
        raise DomainValidationError("report section id must be an integer from 0 to 7") from error


section_title = report_section_title


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportSection:
    id: int | ReportSectionId
    owner_id: str | None = None
    content: str = ""
    facts: tuple[str, ...] = ()
    ai_inferences: tuple[str, ...] = ()
    unconfirmed: tuple[str, ...] = ()
    owner_decisions: tuple[str, ...] = ()
    claim_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=utc_now)
    egress_policy: EgressPolicy = EgressPolicy.LOCAL_ONLY
    provenance: Provenance = field(default_factory=Provenance)

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner_id", _identifier(self.owner_id, "owner_id"))
        if isinstance(self.id, bool) or not isinstance(self.id, (int, ReportSectionId)):
            raise DomainValidationError("report section id must be an integer from 0 to 7")
        try:
            section_id = ReportSectionId(self.id)
        except (TypeError, ValueError) as error:
            raise DomainValidationError("report section id must be an integer from 0 to 7") from error
        object.__setattr__(self, "id", section_id)
        object.__setattr__(self, "content", _text(self.content, "content", allow_empty=True))
        object.__setattr__(self, "facts", _strings(self.facts, "facts"))
        object.__setattr__(self, "ai_inferences", _strings(self.ai_inferences, "ai_inferences"))
        object.__setattr__(self, "unconfirmed", _strings(self.unconfirmed, "unconfirmed"))
        object.__setattr__(self, "owner_decisions", _strings(self.owner_decisions, "owner_decisions"))
        object.__setattr__(self, "claim_ids", _strings(self.claim_ids, "claim_ids"))
        object.__setattr__(self, "evidence_ids", _strings(self.evidence_ids, "evidence_ids"))
        object.__setattr__(self, "created_at", _required_timestamp(self.created_at, "created_at"))
        object.__setattr__(self, "egress_policy", _enum(self.egress_policy, EgressPolicy, "egress_policy"))
        if not isinstance(self.provenance, Provenance):
            raise DomainValidationError("provenance must be a Provenance")
        _validate_provenance_target(self.provenance, str(self.id))

    @property
    def section_id(self) -> int:
        return int(self.id)

    @property
    def title(self) -> str:
        return report_section_title(self.id)

    @property
    def citations(self) -> tuple[str, ...]:
        return self.evidence_ids

    @property
    def is_non_empty(self) -> bool:
        return bool(self.content.strip() or self.facts or self.ai_inferences or self.unconfirmed or self.owner_decisions or self.claim_ids or self.evidence_ids)

    @property
    def node_type(self) -> NodeType:
        return NodeType.REPORT_SECTION


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportVersion:
    owner_id: str | None = None
    sections: tuple[ReportSection, ...] | Mapping[int, ReportSection]
    id: str = field(default_factory=lambda: new_id("report"))
    parent_id: str | None = None
    supersedes_id: str | None = None
    change_reason: str = "initial"
    metadata: Mapping[str, Any] = field(default_factory=dict)
    financial_formulas: Any = field(default_factory=dict)
    decision_criteria: Any = field(default_factory=dict)
    run_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    status: ReportStatus = ReportStatus.DRAFT
    egress_policy: EgressPolicy = EgressPolicy.LOCAL_ONLY
    final: bool | None = None
    created_at: datetime = field(default_factory=utc_now)
    provenance: Provenance = field(default_factory=Provenance)

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner_id", _identifier(self.owner_id, "owner_id"))
        object.__setattr__(self, "id", _identifier(self.id, "id"))
        if isinstance(self.sections, Mapping):
            values = tuple(self.sections.values())
        else:
            values = tuple(self.sections)
        if not all(isinstance(section, ReportSection) for section in values):
            raise DomainValidationError("report sections must be ReportSection values")
        if len(values) != 8 or {int(section.id) for section in values} != set(range(8)):
            raise DomainValidationError("report version requires exactly 8 unique sections")
        if any(section.owner_id != self.owner_id for section in values):
            raise DomainValidationError("report sections must have the same owner")
        object.__setattr__(self, "sections", tuple(sorted(values, key=lambda section: int(section.id))))
        object.__setattr__(self, "parent_id", _identifier(self.parent_id, "parent_id") if self.parent_id else None)
        object.__setattr__(self, "supersedes_id", _identifier(self.supersedes_id, "supersedes_id") if self.supersedes_id else None)
        if self.parent_id and self.supersedes_id and self.parent_id != self.supersedes_id:
            raise DomainValidationError("parent_id and supersedes_id must agree")
        if self.parent_id and not self.supersedes_id:
            object.__setattr__(self, "supersedes_id", self.parent_id)
        if self.supersedes_id and not self.parent_id:
            object.__setattr__(self, "parent_id", self.supersedes_id)
        object.__setattr__(self, "change_reason", _text(self.change_reason, "change_reason"))
        object.__setattr__(self, "metadata", _freeze(self.metadata))
        object.__setattr__(self, "financial_formulas", _freeze(self.financial_formulas))
        object.__setattr__(self, "decision_criteria", _freeze(self.decision_criteria))
        object.__setattr__(self, "run_ids", _strings(self.run_ids, "run_ids"))
        object.__setattr__(self, "evidence_ids", _strings(self.evidence_ids, "evidence_ids"))
        object.__setattr__(self, "status", _enum(self.status, ReportStatus, "status"))
        object.__setattr__(self, "egress_policy", _enum(self.egress_policy, EgressPolicy, "egress_policy"))
        if self.final is not None:
            if not isinstance(self.final, bool):
                raise DomainValidationError("final must be a boolean")
            expected = ReportStatus.FINAL if self.final else ReportStatus.DRAFT
            if self.status is not expected and self.status is not ReportStatus.DRAFT:
                raise DomainValidationError("final and status must agree")
            object.__setattr__(self, "status", expected)
        object.__setattr__(self, "final", self.status is ReportStatus.FINAL)
        if self.status is ReportStatus.FINAL:
            if not self.run_ids or not self.evidence_ids:
                raise DomainValidationError("final report requires runs and evidence")
            if not all(section.claim_ids and section.evidence_ids for section in self.sections):
                raise DomainValidationError("final report requires claim and evidence references in every section")
            _validate_final_report_contract(
                self.financial_formulas,
                self.decision_criteria,
            )
        object.__setattr__(self, "created_at", _required_timestamp(self.created_at, "created_at"))
        if not isinstance(self.provenance, Provenance):
            raise DomainValidationError("provenance must be a Provenance")
        _validate_provenance_target(self.provenance, self.id)

    @property
    def node_type(self) -> NodeType:
        return NodeType.REPORT_VERSION

    @property
    def title_map(self) -> Mapping[int, str]:
        return MappingProxyType({int(section.id): section.title for section in self.sections})


@dataclass(frozen=True, slots=True, kw_only=True)
class Organization:
    name: str
    owner_id: str | None = None
    id: str = field(default_factory=lambda: new_id("organization"))
    description: str = ""
    status: Status = Status.ACTIVE
    egress_policy: EgressPolicy = EgressPolicy.LOCAL_ONLY
    created_at: datetime = field(default_factory=utc_now)
    provenance: Provenance = field(default_factory=Provenance)

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner_id", _identifier(self.owner_id, "owner_id"))
        object.__setattr__(self, "id", _identifier(self.id, "id"))
        object.__setattr__(self, "name", _text(self.name, "name"))
        object.__setattr__(self, "description", _text(self.description, "description", allow_empty=True))
        object.__setattr__(self, "status", _enum(self.status, Status, "status"))
        object.__setattr__(self, "egress_policy", _enum(self.egress_policy, EgressPolicy, "egress_policy"))
        object.__setattr__(self, "created_at", _required_timestamp(self.created_at, "created_at"))
        if not isinstance(self.provenance, Provenance):
            raise DomainValidationError("provenance must be a Provenance")
        _validate_provenance_target(self.provenance, self.id)

    @property
    def node_type(self) -> NodeType:
        return NodeType.ORGANIZATION


@dataclass(frozen=True, slots=True, kw_only=True)
class Source:
    """The logical source whose immutable content is stored in revisions."""

    title: str
    owner_id: str | None = None
    id: str = field(default_factory=lambda: new_id("source"))
    kind: MaterialKind = MaterialKind.NOTE
    locator: str | None = None
    current_revision_id: str | None = None
    revision: int = 0
    egress_policy: EgressPolicy = EgressPolicy.LOCAL_ONLY
    status: Status = Status.ACTIVE
    created_at: datetime = field(default_factory=utc_now)
    provenance: Provenance = field(default_factory=Provenance)

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner_id", _identifier(self.owner_id, "owner_id"))
        object.__setattr__(self, "id", _identifier(self.id, "id"))
        object.__setattr__(self, "title", _text(self.title, "title"))
        object.__setattr__(self, "kind", _enum(self.kind, MaterialKind, "kind"))
        if self.locator is not None:
            object.__setattr__(self, "locator", _identifier(self.locator, "locator"))
        if self.current_revision_id is not None:
            object.__setattr__(self, "current_revision_id", _identifier(self.current_revision_id, "current_revision_id"))
        if not isinstance(self.revision, int) or isinstance(self.revision, bool) or self.revision < 0:
            raise DomainValidationError("source revision must be a non-negative integer")
        object.__setattr__(self, "egress_policy", _enum(self.egress_policy, EgressPolicy, "egress_policy"))
        object.__setattr__(self, "status", _enum(self.status, Status, "status"))
        object.__setattr__(self, "created_at", _required_timestamp(self.created_at, "created_at"))
        if not isinstance(self.provenance, Provenance):
            raise DomainValidationError("provenance must be a Provenance")
        _validate_provenance_target(self.provenance, self.id)

    @property
    def source_id(self) -> str:
        return self.id

    @property
    def source_kind(self) -> MaterialKind:
        return self.kind

    @property
    def node_type(self) -> NodeType:
        return NodeType.SOURCE

    def egress_projection(
        self,
        *,
        authorization: CampaignAuthorizationSnapshot | None = None,
        authorization_snapshot: CampaignAuthorizationSnapshot | None = None,
        campaign: ResearchCampaign | None = None,
        authorization_registry: CampaignAuthorizationRegistry | None = None,
        registry: CampaignAuthorizationRegistry | None = None,
        current_context: CampaignAuthorizationRegistry | None = None,
        at: datetime | None = None,
    ) -> dict[str, object]:
        return project_shareable(
            self,
            authorization=authorization,
            authorization_snapshot=authorization_snapshot,
            campaign=campaign,
            authorization_registry=authorization_registry,
            registry=registry,
            current_context=current_context,
            at=at,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceRevision:
    source_id: str
    content: str
    owner_id: str | None = None
    revision: int = 1
    id: str = field(default_factory=lambda: new_id("source-revision"))
    supersedes_id: str | None = None
    locator: str | None = None
    content_hash: str | None = None
    retrieved_at: datetime = field(default_factory=utc_now)
    egress_policy: EgressPolicy = EgressPolicy.LOCAL_ONLY
    status: Status = Status.ACTIVE
    provenance: Provenance = field(default_factory=Provenance)

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner_id", _identifier(self.owner_id, "owner_id"))
        object.__setattr__(self, "source_id", _identifier(self.source_id, "source_id"))
        object.__setattr__(self, "id", _identifier(self.id, "id"))
        if not isinstance(self.revision, int) or isinstance(self.revision, bool) or self.revision < 1:
            raise DomainValidationError("source revision must be a positive integer")
        if self.supersedes_id is not None:
            object.__setattr__(self, "supersedes_id", _identifier(self.supersedes_id, "supersedes_id"))
            if self.supersedes_id == self.id:
                raise DomainValidationError("source revision cannot supersede itself")
        object.__setattr__(self, "content", _text(self.content, "content", allow_empty=True))
        digest = sha256(self.content.encode("utf-8")).hexdigest()
        supplied = _identifier(self.content_hash or digest, "content_hash").lower()
        if supplied != digest:
            raise DomainValidationError("content_hash must match content")
        object.__setattr__(self, "content_hash", supplied)
        if self.locator is not None:
            object.__setattr__(self, "locator", _identifier(self.locator, "locator"))
        object.__setattr__(self, "retrieved_at", _required_timestamp(self.retrieved_at, "retrieved_at"))
        object.__setattr__(self, "egress_policy", _enum(self.egress_policy, EgressPolicy, "egress_policy"))
        object.__setattr__(self, "status", _enum(self.status, Status, "status"))
        if not isinstance(self.provenance, Provenance):
            raise DomainValidationError("provenance must be a Provenance")
        _validate_provenance_target(self.provenance, self.id)

    @property
    def hash(self) -> str:
        return self.content_hash

    @property
    def revision_number(self) -> int:
        return self.revision

    @property
    def node_type(self) -> NodeType:
        return NodeType.SOURCE_REVISION

    def egress_projection(
        self,
        *,
        authorization: CampaignAuthorizationSnapshot | None = None,
        authorization_snapshot: CampaignAuthorizationSnapshot | None = None,
        campaign: ResearchCampaign | None = None,
        authorization_registry: CampaignAuthorizationRegistry | None = None,
        registry: CampaignAuthorizationRegistry | None = None,
        current_context: CampaignAuthorizationRegistry | None = None,
        at: datetime | None = None,
    ) -> dict[str, object]:
        return project_shareable(
            self,
            authorization=authorization,
            authorization_snapshot=authorization_snapshot,
            campaign=campaign,
            authorization_registry=authorization_registry,
            registry=registry,
            current_context=current_context,
            at=at,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class EntityRevision:
    """An immutable revision belonging to a stable entity anchor.

    The anchor keeps its identity while this value records one immutable
    public projection.  Raw or private material is represented only by a
    local reference and never copied into ``public_payload``.
    """

    entity_id: str
    entity_type: NodeType | str
    revision: int
    payload_schema: str
    public_payload: Mapping[str, Any] = field(default_factory=dict)
    owner_id: str | None = None
    id: str = field(default_factory=lambda: new_id("entity-revision"))
    local_content_ref: str | None = None
    content_hash: str | None = None
    status: Status = Status.ACTIVE
    egress_policy: EgressPolicy = EgressPolicy.LOCAL_ONLY
    created_at: datetime = field(default_factory=utc_now)
    provenance_id: str | None = None
    provenance: Provenance = field(default_factory=Provenance)

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner_id", _identifier(self.owner_id, "owner_id"))
        object.__setattr__(self, "id", _identifier(self.id, "id"))
        object.__setattr__(self, "entity_id", _identifier(self.entity_id, "entity_id"))
        if self.entity_id == self.id:
            raise DomainValidationError("entity_id must differ from revision id")
        entity_type = _node_type(self.entity_type, "entity_type")
        if entity_type in {NodeType.ENTITY_REVISION, NodeType.RELATION_ASSERTION, NodeType.CONTENT_CHUNK}:
            raise DomainValidationError("entity_type must identify a stable entity anchor")
        object.__setattr__(self, "entity_type", entity_type)
        if not isinstance(self.revision, int) or isinstance(self.revision, bool) or self.revision < 1:
            raise DomainValidationError("entity revision must be a positive integer")
        object.__setattr__(self, "payload_schema", _identifier(self.payload_schema, "payload_schema"))
        frozen_payload = _freeze(self.public_payload, "public_payload")
        if not isinstance(frozen_payload, Mapping):
            raise DomainValidationError("public_payload must be a mapping")
        object.__setattr__(self, "public_payload", frozen_payload)
        digest = _json_content_hash(frozen_payload)
        supplied_hash = _identifier(self.content_hash or digest, "content_hash").lower()
        if supplied_hash != digest:
            raise DomainValidationError("content_hash must match public_payload")
        object.__setattr__(self, "content_hash", supplied_hash)
        if self.local_content_ref is not None:
            object.__setattr__(self, "local_content_ref", _identifier(self.local_content_ref, "local_content_ref"))
        object.__setattr__(self, "status", _enum(self.status, Status, "status"))
        object.__setattr__(self, "egress_policy", _enum(self.egress_policy, EgressPolicy, "egress_policy"))
        object.__setattr__(self, "created_at", _required_timestamp(self.created_at, "created_at"))
        if not isinstance(self.provenance, Provenance):
            raise DomainValidationError("provenance must be a Provenance")
        object.__setattr__(self, "provenance_id", _identifier(self.provenance_id or self.provenance.idempotency_key, "provenance_id"))
        _validate_provenance_target(self.provenance, self.id)

    @property
    def node_type(self) -> NodeType:
        return NodeType.ENTITY_REVISION

    def egress_projection(self, **kwargs: Any) -> dict[str, object]:
        return project_shareable(self, **kwargs)


@dataclass(frozen=True, slots=True, kw_only=True)
class ContentChunk:
    """A stable, citeable range within one immutable source revision."""

    source_revision_id: str
    ordinal: int
    char_start: int
    char_end: int
    text: str = ""
    owner_id: str | None = None
    id: str = field(default_factory=lambda: new_id("content-chunk"))
    content_locator: str | None = None
    text_hash: str | None = None
    status: Status = Status.ACTIVE
    egress_policy: EgressPolicy = EgressPolicy.LOCAL_ONLY
    created_at: datetime = field(default_factory=utc_now)
    provenance_id: str | None = None
    provenance: Provenance = field(default_factory=Provenance)

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner_id", _identifier(self.owner_id, "owner_id"))
        object.__setattr__(self, "id", _identifier(self.id, "id"))
        object.__setattr__(self, "source_revision_id", _identifier(self.source_revision_id, "source_revision_id"))
        if not isinstance(self.ordinal, int) or isinstance(self.ordinal, bool) or self.ordinal < 0:
            raise DomainValidationError("ordinal must be a non-negative integer")
        if not isinstance(self.char_start, int) or isinstance(self.char_start, bool) or self.char_start < 0:
            raise DomainValidationError("char_start must be a non-negative integer")
        if not isinstance(self.char_end, int) or isinstance(self.char_end, bool) or self.char_end <= self.char_start:
            raise DomainValidationError("char_end must be greater than char_start")
        object.__setattr__(self, "text", _text(self.text, "text", allow_empty=True))
        if not self.text and self.content_locator is None:
            raise DomainValidationError("content chunk requires text or content_locator")
        if self.content_locator is not None:
            object.__setattr__(self, "content_locator", _identifier(self.content_locator, "content_locator"))
        digest = sha256(self.text.encode("utf-8")).hexdigest()
        supplied_hash = _identifier(self.text_hash or digest, "text_hash").lower()
        if self.text and supplied_hash != digest:
            raise DomainValidationError("text_hash must match text")
        object.__setattr__(self, "text_hash", supplied_hash)
        object.__setattr__(self, "status", _enum(self.status, Status, "status"))
        object.__setattr__(self, "egress_policy", _enum(self.egress_policy, EgressPolicy, "egress_policy"))
        object.__setattr__(self, "created_at", _required_timestamp(self.created_at, "created_at"))
        if not isinstance(self.provenance, Provenance):
            raise DomainValidationError("provenance must be a Provenance")
        object.__setattr__(self, "provenance_id", _identifier(self.provenance_id or self.provenance.idempotency_key, "provenance_id"))
        _validate_provenance_target(self.provenance, self.id)

    @property
    def node_type(self) -> NodeType:
        return NodeType.CONTENT_CHUNK

    def egress_projection(self, **kwargs: Any) -> dict[str, object]:
        return project_shareable(self, **kwargs)


CONTENT_CHUNK_TARGET_LENGTH = 2_400
CONTENT_CHUNK_MAX_LENGTH = 4_000


def deterministic_content_chunk_id(
    source_revision_id: str,
    char_start: int,
    char_end: int,
    text: str,
) -> str:
    """Return the stable identity for one source-revision text range."""

    if not isinstance(source_revision_id, str) or not source_revision_id.strip():
        raise DomainValidationError("source_revision_id must be a non-empty string")
    if not isinstance(char_start, int) or isinstance(char_start, bool) or char_start < 0:
        raise DomainValidationError("char_start must be a non-negative integer")
    if not isinstance(char_end, int) or isinstance(char_end, bool) or char_end <= char_start:
        raise DomainValidationError("char_end must be greater than char_start")
    if not isinstance(text, str) or not text:
        raise DomainValidationError("content chunk text must not be empty")
    identity = "\x00".join((source_revision_id.strip(), str(char_start), str(char_end)))
    digest = sha256(identity.encode("utf-8") + b"\x00" + text.encode("utf-8")).hexdigest()
    return f"content-chunk_{digest}"


def _paragraph_boundaries(content: str, start: int, limit: int) -> tuple[int, ...]:
    boundaries: list[int] = []
    index = start
    while index < limit:
        if content[index] not in "\r\n":
            index += 1
            continue
        end = index
        newline_count = 0
        while end < limit and content[end] in "\r\n":
            if content[end] == "\r" and end + 1 < len(content) and content[end + 1] == "\n":
                end += 2
            else:
                end += 1
            newline_count += 1
        if newline_count >= 2 and end <= limit:
            boundaries.append(end)
        index = end
    return tuple(boundaries)


def _sentence_boundaries(content: str, start: int, limit: int) -> tuple[int, ...]:
    terminators = frozenset(".!?。！？")
    closers = frozenset("\"'”’»）】〕〉》")
    boundaries: list[int] = []
    index = start
    while index < limit:
        if content[index] not in terminators:
            index += 1
            continue
        end = index + 1
        while end < limit and content[end] in closers:
            end += 1
        if end < len(content) and not content[end].isspace():
            index += 1
            continue
        while end < limit and content[end].isspace():
            end += 1
        if end <= limit:
            boundaries.append(end)
        index = end
    return tuple(boundaries)


def _whitespace_boundaries(content: str, start: int, limit: int) -> tuple[int, ...]:
    boundaries: list[int] = []
    index = start
    while index < limit:
        if not content[index].isspace():
            index += 1
            continue
        end = index + 1
        while end < limit and content[end].isspace():
            end += 1
        boundaries.append(end)
        index = end
    return tuple(boundaries)


def _select_chunk_boundary(
    content: str,
    start: int,
    target: int,
    maximum: int,
) -> int:
    """Select a preferred structural boundary, or hard-split at maximum."""

    boundary_candidates = (
        _paragraph_boundaries(content, start, maximum),
        _sentence_boundaries(content, start, maximum),
        _whitespace_boundaries(content, start, maximum),
    )
    for candidates in boundary_candidates:
        candidates = tuple(candidate for candidate in candidates if start < candidate <= target)
        if not candidates:
            continue
        return max(candidates)
    for candidates in boundary_candidates:
        candidates = tuple(candidate for candidate in candidates if target < candidate <= maximum)
        if candidates:
            return min(candidates)
    return maximum


def split_source_content(
    content: str,
    *,
    target_length: int = CONTENT_CHUNK_TARGET_LENGTH,
    max_length: int = CONTENT_CHUNK_MAX_LENGTH,
) -> tuple[tuple[int, int, str], ...]:
    """Split content into contiguous Unicode-codepoint ranges.

    Structural boundaries are preferred in paragraph, sentence, and whitespace
    order. The returned text slices concatenate exactly to the input string.
    """

    if not isinstance(content, str):
        raise DomainValidationError("source content must be a string")
    if (
        not isinstance(target_length, int)
        or isinstance(target_length, bool)
        or target_length < 1
        or not isinstance(max_length, int)
        or isinstance(max_length, bool)
        or max_length < target_length
    ):
        raise DomainValidationError("chunk lengths must be positive integers with max_length >= target_length")
    if not content:
        return ()

    chunks: list[tuple[int, int, str]] = []
    start = 0
    content_length = len(content)
    while start < content_length:
        remaining = content_length - start
        if remaining <= max_length:
            end = content_length
        else:
            target = min(start + target_length, content_length)
            maximum = min(start + max_length, content_length)
            end = _select_chunk_boundary(content, start, target, maximum)
        if end <= start:
            raise DomainValidationError("chunk splitter produced an empty range")
        chunks.append((start, end, content[start:end]))
        start = end
    return tuple(chunks)


def build_content_chunks(source_revision: SourceRevision, *, operation: str = "capture_idea") -> tuple[ContentChunk, ...]:
    """Build deterministic, local-only chunks for one immutable revision."""

    if not isinstance(source_revision, SourceRevision):
        raise DomainValidationError("content chunks require a SourceRevision")
    chunks: list[ContentChunk] = []
    for ordinal, (char_start, char_end, text) in enumerate(split_source_content(source_revision.content)):
        chunk_id = deterministic_content_chunk_id(source_revision.id, char_start, char_end, text)
        chunks.append(
            ContentChunk(
                owner_id=source_revision.owner_id,
                id=chunk_id,
                source_revision_id=source_revision.id,
                ordinal=ordinal,
                char_start=char_start,
                char_end=char_end,
                text=text,
                egress_policy=EgressPolicy.LOCAL_ONLY,
                created_at=source_revision.retrieved_at,
                provenance=Provenance(
                    actor="local-owner",
                    operation=operation,
                    target_id=chunk_id,
                    source_id=source_revision.id,
                    occurred_at=source_revision.retrieved_at,
                    idempotency_key=f"content-chunk:{chunk_id}",
                ),
            )
        )
    return tuple(chunks)


@dataclass(frozen=True, slots=True, kw_only=True)
class Facet:
    """A reusable classification term, scoped to the local owner."""

    namespace: str
    value: str
    owner_id: str | None = None
    id: str = field(default_factory=lambda: new_id("facet"))
    normalized_value: str = field(init=False)
    status: Status = Status.ACTIVE
    egress_policy: EgressPolicy = EgressPolicy.LOCAL_ONLY
    created_at: datetime = field(default_factory=utc_now)
    provenance_id: str | None = None
    provenance: Provenance = field(default_factory=Provenance)

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner_id", _identifier(self.owner_id, "owner_id"))
        object.__setattr__(self, "id", _identifier(self.id, "id"))
        object.__setattr__(self, "namespace", _identifier(self.namespace, "namespace"))
        value = _text(self.value, "value")
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "normalized_value", value.strip().casefold())
        object.__setattr__(self, "status", _enum(self.status, Status, "status"))
        object.__setattr__(self, "egress_policy", _enum(self.egress_policy, EgressPolicy, "egress_policy"))
        object.__setattr__(self, "created_at", _required_timestamp(self.created_at, "created_at"))
        if not isinstance(self.provenance, Provenance):
            raise DomainValidationError("provenance must be a Provenance")
        object.__setattr__(self, "provenance_id", _identifier(self.provenance_id or self.provenance.idempotency_key, "provenance_id"))
        _validate_provenance_target(self.provenance, self.id)

    @property
    def node_type(self) -> NodeType:
        return NodeType.FACET

    def egress_projection(self, **kwargs: Any) -> dict[str, object]:
        return project_shareable(self, **kwargs)


@dataclass(frozen=True, slots=True, kw_only=True)
class RelationAssertion:
    """An immutable, evidence-aware semantic relation between two anchors."""

    source_id: str
    target_id: str
    source_kind: NodeType | str
    target_kind: NodeType | str
    predicate: RelationType | str
    assertion_family_id: str
    owner_id: str | None = None
    id: str = field(default_factory=lambda: new_id("relation-assertion"))
    revision: int = 1
    status: RelationshipStatus = RelationshipStatus.PROPOSED
    confidence: float | None = None
    evidence_ids: tuple[str, ...] = ()
    valid_from: datetime = field(default_factory=utc_now)
    expires_at: datetime | None = None
    supersedes_id: str | None = None
    egress_policy: EgressPolicy = EgressPolicy.LOCAL_ONLY
    provenance_id: str | None = None
    provenance: Provenance = field(default_factory=Provenance)
    based_on_brief_id: str | None = None
    based_on_brief_section_index: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner_id", _identifier(self.owner_id, "owner_id"))
        object.__setattr__(self, "id", _identifier(self.id, "id"))
        object.__setattr__(self, "source_id", _identifier(self.source_id, "source_id"))
        object.__setattr__(self, "target_id", _identifier(self.target_id, "target_id"))
        source_kind = _node_type(self.source_kind, "source_kind")
        target_kind = _node_type(self.target_kind, "target_kind")
        object.__setattr__(self, "source_kind", source_kind)
        object.__setattr__(self, "target_kind", target_kind)
        predicate = _enum(self.predicate, RelationType, "predicate")
        object.__setattr__(self, "predicate", predicate)
        allowed_endpoints = _ALLOWED_RELATION_ENDPOINTS.get(predicate, frozenset())
        if (source_kind, target_kind) not in allowed_endpoints:
            raise DomainValidationError("relation assertion endpoint kinds are not allowed")
        object.__setattr__(self, "assertion_family_id", _identifier(self.assertion_family_id, "assertion_family_id"))
        if not isinstance(self.revision, int) or isinstance(self.revision, bool) or self.revision < 1:
            raise DomainValidationError("relation assertion revision must be a positive integer")
        status = _enum(self.status, RelationshipStatus, "status")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "confidence", _confidence(self.confidence))
        object.__setattr__(self, "evidence_ids", _strings(self.evidence_ids, "evidence_ids"))
        if status in {RelationshipStatus.INFERRED, RelationshipStatus.CONFIRMED} and not self.evidence_ids:
            raise DomainValidationError("inferred and confirmed relation assertions require evidence")
        if predicate in {RelationType.CAN_CONTRIBUTE_TO, RelationType.INTRODUCED_BY}:
            if status not in {RelationshipStatus.PROPOSED, RelationshipStatus.INFERRED}:
                raise DomainValidationError("network relations must be proposed or inferred")
            if self.confidence is None:
                raise DomainValidationError("network relation assertions require confidence")
            if self.expires_at is None:
                raise DomainValidationError("network relation assertions require an expiration")
        object.__setattr__(self, "valid_from", _required_timestamp(self.valid_from, "valid_from"))
        expires_at = _timestamp(self.expires_at, "expires_at")
        if expires_at is not None and expires_at <= self.valid_from:
            raise DomainValidationError("expires_at must be after valid_from")
        object.__setattr__(self, "expires_at", expires_at)
        if self.supersedes_id is not None:
            supersedes_id = _identifier(self.supersedes_id, "supersedes_id")
            if supersedes_id == self.id:
                raise DomainValidationError("relation assertion cannot supersede itself")
            object.__setattr__(self, "supersedes_id", supersedes_id)
        if (self.based_on_brief_id is None) != (self.based_on_brief_section_index is None):
            raise DomainValidationError("based_on_brief_id and section index must be provided together")
        if self.based_on_brief_id is not None:
            object.__setattr__(self, "based_on_brief_id", _identifier(self.based_on_brief_id, "based_on_brief_id"))
            if type(self.based_on_brief_section_index) is not int or not 0 <= self.based_on_brief_section_index <= 7:
                raise DomainValidationError("brief section index must be an integer from 0 to 7")
        object.__setattr__(self, "egress_policy", _enum(self.egress_policy, EgressPolicy, "egress_policy"))
        if not isinstance(self.provenance, Provenance):
            raise DomainValidationError("provenance must be a Provenance")
        object.__setattr__(self, "provenance_id", _identifier(self.provenance_id or self.provenance.idempotency_key, "provenance_id"))
        _validate_provenance_target(self.provenance, self.id)

    @property
    def node_type(self) -> NodeType:
        return NodeType.RELATION_ASSERTION

    def egress_projection(self, **kwargs: Any) -> dict[str, object]:
        return project_shareable(self, **kwargs)


def relation_assertion_structural_edges(
    assertion: RelationAssertion,
) -> tuple[tuple[str, str, str], ...]:
    """Return canonical structural refs for a validated assertion value.

    Callers must resolve and validate all referenced records before storing
    these triples. This helper fixes labels and direction; it is not proof
    that any endpoint or Evidence exists.
    """
    if not isinstance(assertion, RelationAssertion):
        raise DomainValidationError("structural edges require a RelationAssertion")
    if len(assertion.evidence_ids) != len(set(assertion.evidence_ids)):
        raise DomainValidationError("relation assertion Evidence IDs must be unique")
    edges = [
        (assertion.id, RelationAssertionEdgeType.ASSERTS_FROM.value, assertion.source_id),
        (assertion.id, RelationAssertionEdgeType.ASSERTS_TO.value, assertion.target_id),
        *(
            (assertion.id, RelationAssertionEdgeType.EVIDENCED_BY.value, evidence_id)
            for evidence_id in assertion.evidence_ids
        ),
    ]
    if assertion.supersedes_id is not None:
        edges.append((assertion.id, RelationAssertionEdgeType.SUPERSEDES.value, assertion.supersedes_id))
    return tuple(edges)


@dataclass(frozen=True, slots=True, kw_only=True)
class OwnerProfile:
    owner_id: str | None = None
    id: str | None = None
    display_name: str = ""
    status: Status = Status.ACTIVE
    egress_policy: EgressPolicy = EgressPolicy.LOCAL_ONLY
    created_at: datetime = field(default_factory=utc_now)
    provenance: Provenance = field(default_factory=Provenance)

    def __post_init__(self) -> None:
        owner = _identifier(self.owner_id, "owner_id")
        object.__setattr__(self, "owner_id", owner)
        object.__setattr__(self, "id", _identifier(self.id or owner, "id"))
        object.__setattr__(self, "display_name", _text(self.display_name, "display_name", allow_empty=True))
        object.__setattr__(self, "status", _enum(self.status, Status, "status"))
        object.__setattr__(self, "egress_policy", _enum(self.egress_policy, EgressPolicy, "egress_policy"))
        object.__setattr__(self, "created_at", _required_timestamp(self.created_at, "created_at"))
        if not isinstance(self.provenance, Provenance):
            raise DomainValidationError("provenance must be a Provenance")
        _validate_provenance_target(self.provenance, self.id)

    @property
    def node_type(self) -> NodeType:
        return NodeType.OWNER_PROFILE


@dataclass(frozen=True, slots=True, kw_only=True)
class Decision:
    text: str
    owner_id: str | None = None
    id: str = field(default_factory=lambda: new_id("decision"))
    claim_ids: tuple[str, ...] = ()
    report_ids: tuple[str, ...] = ()
    experiment_ids: tuple[str, ...] = ()
    status: Status = Status.ACTIVE
    egress_policy: EgressPolicy = EgressPolicy.LOCAL_ONLY
    created_at: datetime = field(default_factory=utc_now)
    provenance: Provenance = field(default_factory=Provenance)

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner_id", _identifier(self.owner_id, "owner_id"))
        object.__setattr__(self, "id", _identifier(self.id, "id"))
        object.__setattr__(self, "text", _text(self.text, "text"))
        object.__setattr__(self, "claim_ids", _strings(self.claim_ids, "claim_ids"))
        object.__setattr__(self, "report_ids", _strings(self.report_ids, "report_ids"))
        object.__setattr__(self, "experiment_ids", _strings(self.experiment_ids, "experiment_ids"))
        object.__setattr__(self, "status", _enum(self.status, Status, "status"))
        object.__setattr__(self, "egress_policy", _enum(self.egress_policy, EgressPolicy, "egress_policy"))
        object.__setattr__(self, "created_at", _required_timestamp(self.created_at, "created_at"))
        if not isinstance(self.provenance, Provenance):
            raise DomainValidationError("provenance must be a Provenance")
        _validate_provenance_target(self.provenance, self.id)

    @property
    def node_type(self) -> NodeType:
        return NodeType.DECISION


@dataclass(frozen=True, slots=True, kw_only=True)
class Experiment:
    name: str
    owner_id: str | None = None
    id: str = field(default_factory=lambda: new_id("experiment"))
    success_criteria: tuple[str, ...] = ()
    stop_criteria: tuple[str, ...] = ()
    status: Status = Status.DRAFT
    egress_policy: EgressPolicy = EgressPolicy.LOCAL_ONLY
    created_at: datetime = field(default_factory=utc_now)
    provenance: Provenance = field(default_factory=Provenance)

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner_id", _identifier(self.owner_id, "owner_id"))
        object.__setattr__(self, "id", _identifier(self.id, "id"))
        object.__setattr__(self, "name", _text(self.name, "name"))
        object.__setattr__(self, "success_criteria", _strings(self.success_criteria, "success_criteria"))
        object.__setattr__(self, "stop_criteria", _strings(self.stop_criteria, "stop_criteria"))
        object.__setattr__(self, "status", _enum(self.status, Status, "status"))
        object.__setattr__(self, "egress_policy", _enum(self.egress_policy, EgressPolicy, "egress_policy"))
        object.__setattr__(self, "created_at", _required_timestamp(self.created_at, "created_at"))
        if not isinstance(self.provenance, Provenance):
            raise DomainValidationError("provenance must be a Provenance")
        _validate_provenance_target(self.provenance, self.id)

    @property
    def node_type(self) -> NodeType:
        return NodeType.EXPERIMENT


@dataclass(frozen=True, slots=True, kw_only=True)
class InstructionArtifact:
    path: str
    owner_id: str | None = None
    id: str = field(default_factory=lambda: new_id("instruction"))
    scope: str = ""
    content_hash: str | None = None
    status: Status = Status.ACTIVE
    egress_policy: EgressPolicy = EgressPolicy.LOCAL_ONLY
    created_at: datetime = field(default_factory=utc_now)
    provenance: Provenance = field(default_factory=Provenance)

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner_id", _identifier(self.owner_id, "owner_id"))
        object.__setattr__(self, "id", _identifier(self.id, "id"))
        object.__setattr__(self, "path", _text(self.path, "path"))
        object.__setattr__(self, "scope", _text(self.scope, "scope", allow_empty=True))
        if self.content_hash is not None:
            object.__setattr__(self, "content_hash", _identifier(self.content_hash, "content_hash"))
        object.__setattr__(self, "status", _enum(self.status, Status, "status"))
        object.__setattr__(self, "egress_policy", _enum(self.egress_policy, EgressPolicy, "egress_policy"))
        object.__setattr__(self, "created_at", _required_timestamp(self.created_at, "created_at"))
        if not isinstance(self.provenance, Provenance):
            raise DomainValidationError("provenance must be a Provenance")
        _validate_provenance_target(self.provenance, self.id)

    @property
    def node_type(self) -> NodeType:
        return NodeType.INSTRUCTION_ARTIFACT


def _same_owner(*values: Any) -> str:
    owners = {_identifier(value.owner_id, "owner_id") for value in values if value is not None}
    if len(owners) != 1:
        raise DomainValidationError("aggregate references must have the same owner")
    return owners.pop()


def validate_source_revision_history(
    source: Source,
    revisions: Sequence[SourceRevision] | Mapping[str, SourceRevision],
) -> SourceRevision:
    """Validate the immutable, owner-scoped revision chain for one Source.

    The returned value is the unique current revision.  The validator does not
    mutate a Source or a revision; callers advance ``current_revision_id`` by
    creating a new Source value after appending a new SourceRevision.
    """

    if not isinstance(source, Source):
        raise DomainValidationError("source history requires a Source")
    if isinstance(revisions, Mapping):
        revision_values = tuple(revisions.values())
    else:
        try:
            revision_values = tuple(revisions)
        except TypeError as error:
            raise DomainValidationError("source revisions must be a sequence") from error
    if not revision_values:
        raise DomainValidationError("source history requires at least one revision")
    if source.current_revision_id is None:
        raise DomainValidationError("source current_revision_id is required")

    by_id: dict[str, SourceRevision] = {}
    by_number: dict[int, SourceRevision] = {}
    for revision in revision_values:
        if not isinstance(revision, SourceRevision):
            raise DomainValidationError("source history must contain SourceRevision values")
        if revision.source_id != source.id:
            raise DomainValidationError("source revision source_id does not match source")
        if revision.owner_id != source.owner_id:
            raise DomainValidationError("source revision owner does not match source")
        if revision.id in by_id:
            raise DomainValidationError("source revision history contains duplicate revision id")
        if revision.revision in by_number:
            raise DomainValidationError("source revision history contains duplicate revision number")
        by_id[revision.id] = revision
        by_number[revision.revision] = revision

    ordered = sorted(by_number.values(), key=lambda item: item.revision)
    for expected_revision, revision in enumerate(ordered, start=1):
        if revision.revision != expected_revision:
            raise DomainValidationError("source revision numbers must be monotonic and contiguous")
        if expected_revision == 1:
            if revision.supersedes_id is not None:
                raise DomainValidationError("first source revision cannot supersede another revision")
            continue
        prior = ordered[expected_revision - 2]
        if revision.supersedes_id != prior.id:
            raise DomainValidationError("source revision supersedes chain is not monotonic")

    current = by_id.get(source.current_revision_id)
    if current is None:
        raise DomainValidationError("source current_revision_id does not resolve to a revision")
    if current.revision != ordered[-1].revision:
        raise DomainValidationError("source current revision must be the latest revision")
    return current


validate_source_history = validate_source_revision_history
validate_source_revisions = validate_source_revision_history


def validate_campaign_idea_reference(campaign: ResearchCampaign, idea: Idea) -> None:
    if idea is None or campaign.target_idea_id is None or campaign.target_idea_id != idea.id:
        raise DomainValidationError("campaign idea reference does not exist")
    _same_owner(campaign, idea)


def _validate_current_campaign_authorization(
    campaign: ResearchCampaign,
    authorization: CampaignAuthorizationSnapshot,
    *,
    authorization_registry: CampaignAuthorizationRegistry | None = None,
    registry: CampaignAuthorizationRegistry | None = None,
    current_context: CampaignAuthorizationRegistry | None = None,
    at: datetime | None = None,
) -> CampaignAuthorizationSnapshot:
    registries = tuple(
        candidate
        for candidate in (authorization_registry, registry, current_context)
        if candidate is not None
    )
    if not registries:
        raise DomainValidationError("authoritative registry is required for authorization validation")
    if not all(isinstance(candidate, CampaignAuthorizationRegistry) for candidate in registries):
        raise DomainValidationError("authoritative registry must be CampaignAuthorizationRegistry")
    if any(candidate != registries[0] for candidate in registries[1:]):
        raise DomainValidationError("conflicting authoritative authorization registries")
    authoritative_campaign, current = registries[0].resolve_current(campaign.id)
    if campaign != authoritative_campaign:
        raise DomainValidationError("campaign is not the authoritative current aggregate")
    if authorization.campaign_id != campaign.id or authorization.owner_id != campaign.owner_id:
        raise DomainValidationError("authorization snapshot owner or campaign does not match")
    if (
        authorization.id != current.id
        or authorization.revision != current.revision
        or authorization.owner_id != current.owner_id
        or authorization.expires_at != current.expires_at
        or authorization != current
    ):
        raise DomainValidationError("authorization snapshot is superseded; current snapshot is required")
    if not authorization.is_active(at=at):
        raise DomainValidationError("authorization snapshot is expired")
    return current


def validate_run_campaign_reference(
    run: ResearchRun,
    campaign: ResearchCampaign,
    authorization: CampaignAuthorizationSnapshot,
    *,
    authorization_registry: CampaignAuthorizationRegistry | None = None,
    registry: CampaignAuthorizationRegistry | None = None,
    current_context: CampaignAuthorizationRegistry | None = None,
    at: datetime | None = None,
) -> None:
    if run is None or campaign is None or authorization is None:
        raise DomainValidationError("run requires campaign and authorization snapshot references")
    if run.campaign_id != campaign.id or run.owner_id != campaign.owner_id:
        raise DomainValidationError("run campaign reference does not exist or has a different owner")
    if run.authorization_snapshot_id != authorization.id or run.authorization_revision != authorization.revision:
        raise DomainValidationError("run authorization snapshot reference does not match")
    _validate_current_campaign_authorization(
        campaign,
        authorization,
        authorization_registry=authorization_registry,
        registry=registry,
        current_context=current_context,
        at=at,
    )


def validate_evidence_references(
    evidence: Evidence,
    *,
    material: ResearchMaterial | None = None,
    claim: Claim | None = None,
    source_revision: SourceRevision | None = None,
) -> None:
    if evidence is None:
        raise DomainValidationError("evidence is required")
    if material is not None and (material.id != evidence.material_id or material.owner_id != evidence.owner_id):
        raise DomainValidationError("evidence material reference does not exist or has a different owner")
    if evidence.claim_id is not None:
        if claim is None or claim.id != evidence.claim_id or claim.owner_id != evidence.owner_id:
            raise DomainValidationError("evidence claim reference does not exist or has a different owner")
    if evidence.source_revision_id is not None:
        if source_revision is None or source_revision.id != evidence.source_revision_id or source_revision.owner_id != evidence.owner_id:
            raise DomainValidationError("evidence source revision reference does not exist or has a different owner")
    if material is None and source_revision is None:
        raise DomainValidationError("evidence requires an existing material or source revision reference")


def validate_claim_evidence_references(claim: Claim, evidence: Sequence[Evidence]) -> None:
    if claim is None:
        raise DomainValidationError("claim is required")
    by_id = {item.id: item for item in evidence}
    for evidence_id in claim.evidence_ids:
        item = by_id.get(evidence_id)
        if item is None or item.owner_id != claim.owner_id:
            raise DomainValidationError("claim evidence reference does not exist or has a different owner")
        if item.claim_id != claim.id:
            raise DomainValidationError("claim evidence reference must identify the same claim")


def _normalize_report_reference_sequences(
    evidence: Sequence[Evidence] | Sequence[Claim],
    claims: Sequence[Claim] | Sequence[Evidence],
) -> tuple[Sequence[Evidence], Sequence[Claim]]:
    """Accept both the legacy evidence-third and claims-third call shapes."""

    evidence_values = tuple(evidence)
    claim_values = tuple(claims)
    evidence_is_claims = any(isinstance(item, Claim) for item in evidence_values)
    claims_is_evidence = any(isinstance(item, Evidence) for item in claim_values)
    if evidence_is_claims and (claims_is_evidence or not claim_values):
        return claim_values, evidence_values
    if claims_is_evidence and not evidence_values:
        return claim_values, evidence_values
    return evidence_values, claim_values


def validate_report_references(
    report: ReportVersion,
    runs: Sequence[ResearchRun],
    evidence: Sequence[Evidence] = (),
    claims: Sequence[Claim] = (),
) -> None:
    if report is None:
        raise DomainValidationError("report is required")
    evidence, claims = _normalize_report_reference_sequences(evidence, claims)
    run_by_id = {item.id: item for item in runs}
    claim_by_id = {item.id: item for item in claims}
    evidence_by_id = {item.id: item for item in evidence}
    for run_id in report.run_ids:
        item = run_by_id.get(run_id)
        if item is None or item.owner_id != report.owner_id:
            raise DomainValidationError("report run reference does not exist or has a different owner")
    for evidence_id in report.evidence_ids:
        item = evidence_by_id.get(evidence_id)
        if item is None or item.owner_id != report.owner_id:
            raise DomainValidationError("report evidence reference does not exist or has a different owner")
    for section in report.sections:
        if section.owner_id != report.owner_id:
            raise DomainValidationError("report section reference has a different owner")
        section_claims: dict[str, Claim] = {}
        for claim_id in section.claim_ids:
            item = claim_by_id.get(claim_id)
            if item is None or item.owner_id != report.owner_id or item.owner_id != section.owner_id:
                raise DomainValidationError("report section claim reference does not exist or has a different owner")
            section_claims[claim_id] = item
        for evidence_id in section.evidence_ids:
            item = evidence_by_id.get(evidence_id)
            if item is None or item.owner_id != report.owner_id or item.owner_id != section.owner_id:
                raise DomainValidationError("report section evidence reference does not exist or has a different owner")
            if item.claim_id is None or item.claim_id not in section_claims:
                raise DomainValidationError("report section evidence reference must identify a referenced claim")


def validate_references(
    *,
    campaign: ResearchCampaign | None = None,
    idea: Idea | None = None,
    run: ResearchRun | None = None,
    authorization: CampaignAuthorizationSnapshot | None = None,
    authorization_registry: CampaignAuthorizationRegistry | None = None,
    registry: CampaignAuthorizationRegistry | None = None,
    current_context: CampaignAuthorizationRegistry | None = None,
    evidence: Evidence | None = None,
    material: ResearchMaterial | None = None,
    source: Source | None = None,
    source_revisions: Sequence[SourceRevision] | Mapping[str, SourceRevision] = (),
    source_revision: SourceRevision | None = None,
    claim: Claim | None = None,
    claim_evidence: Sequence[Evidence] | None = None,
    report: ReportVersion | None = None,
    runs: Sequence[ResearchRun] = (),
    report_evidence: Sequence[Evidence] = (),
    report_claims: Sequence[Claim] = (),
    claims: Sequence[Claim] | None = None,
) -> None:
    authorization_inputs = (
        authorization,
        authorization_registry,
        registry,
        current_context,
    )
    if run is None and any(value is not None for value in authorization_inputs):
        raise DomainValidationError("authorization inputs require a run reference")
    if campaign is not None and idea is not None:
        validate_campaign_idea_reference(campaign, idea)
    if run is not None:
        if campaign is None:
            raise DomainValidationError("run requires campaign and authorization snapshot references")
        validate_run_campaign_reference(
            run,
            campaign,
            authorization,
            authorization_registry=authorization_registry,
            registry=registry,
            current_context=current_context,
        )
    if evidence is not None:
        validate_evidence_references(evidence, material=material, claim=claim, source_revision=source_revision)
    if source is not None:
        validate_source_revision_history(source, source_revisions)
    if claim is not None and claim_evidence is not None:
        validate_claim_evidence_references(claim, claim_evidence)
    if report is not None:
        if claims is not None:
            if report_claims and tuple(report_claims) != tuple(claims):
                raise DomainValidationError("conflicting report claim references")
            report_claims = claims
        validate_report_references(report, runs, report_evidence, report_claims)


validate_aggregate_references = validate_references
validate_campaign_reference = validate_campaign_idea_reference
validate_run_reference = validate_run_campaign_reference
validate_evidence_reference = validate_evidence_references
validate_claim_reference = validate_claim_evidence_references
validate_report_reference = validate_report_references


# Schema-v2 value objects are validated by the domain contract first.  They
# join the external read boundary only when DM-04 adds their persisted
# traversal and safe projection contract.
_READ_MCP_NODE_TYPES = frozenset(
    node_type
    for node_type in NodeType
    if node_type
    not in {
        NodeType.ENTITY_REVISION,
        NodeType.RELATION_ASSERTION,
        NodeType.CONTENT_CHUNK,
        NodeType.FACET,
    }
)

# The map is intentionally data-only: callers can inspect the external field
# boundary without deriving it from dataclass fields (which include private
# provenance, owner, and raw input state).
SHAREABLE_PROJECTION_ALLOWLIST = MappingProxyType({
    NodeType.OWNER_PROFILE: ("id", "display_name", "status"),
    NodeType.IDEA: ("id", "title", "summary", "description", "tags", "status"),
    NodeType.ASSET: ("id", "name", "kind", "description", "status"),
    NodeType.PERSON: ("id", "name", "kind", "status"),
    NodeType.ORGANIZATION: ("id", "name", "description", "status"),
    NodeType.SOURCE: ("id", "title", "kind", "locator", "current_revision_id", "revision", "status"),
    NodeType.SOURCE_REVISION: (
        "id",
        "source_id",
        "revision",
        "content",
        "locator",
        "content_hash",
        "retrieved_at",
        "status",
    ),
    NodeType.RESEARCH_MATERIAL: ("id", "title", "kind", "locator", "content_hash", "content"),
    NodeType.CLAIM: ("id", "text", "claim_type", "confidence", "evidence_ids", "status", "revision", "supersedes_id"),
    NodeType.EVIDENCE: (
        "id",
        "polarity",
        "confidence",
        "status",
    ),
    NodeType.RESEARCH_CAMPAIGN: ("id", "purpose", "questions", "target_idea_id", "status"),
    NodeType.RESEARCH_RUN: ("id", "campaign_id", "model_snapshot", "sources", "evidence_ids", "status", "parent_run_id", "supersedes_id"),
    NodeType.REPORT_VERSION: (
        "id",
        "sections",
        "parent_id",
        "supersedes_id",
        "change_reason",
        "financial_formulas",
        "decision_criteria",
        "run_ids",
        "evidence_ids",
        "status",
    ),
    NodeType.REPORT_SECTION: (
        "id",
        "title",
        "content",
        "facts",
        "ai_inferences",
        "unconfirmed",
        "owner_decisions",
        "claim_ids",
        "evidence_ids",
    ),
    NodeType.DECISION: ("id", "text", "claim_ids", "report_ids", "experiment_ids", "status"),
    NodeType.EXPERIMENT: ("id", "name", "success_criteria", "stop_criteria", "status"),
    NodeType.INSTRUCTION_ARTIFACT: ("id", "content_hash", "status"),
    NodeType.ENTITY_REVISION: (
        "id",
        "entity_id",
        "entity_type",
        "revision",
        "payload_schema",
        "public_payload",
        "content_hash",
        "created_at",
        "provenance_id",
        "status",
    ),
    NodeType.RELATION_ASSERTION: (
        "id",
        "source_id",
        "target_id",
        "source_kind",
        "target_kind",
        "predicate",
        "assertion_family_id",
        "revision",
        "status",
        "confidence",
        "evidence_ids",
        "valid_from",
        "expires_at",
        "supersedes_id",
        "provenance_id",
    ),
    NodeType.CONTENT_CHUNK: (
        "id",
        "source_revision_id",
        "ordinal",
        "char_start",
        "char_end",
        "text_hash",
        "status",
    ),
    NodeType.FACET: ("id", "namespace", "normalized_value", "status"),
})
PROJECTION_ALLOWLIST = SHAREABLE_PROJECTION_ALLOWLIST
READ_MCP_NODE_TYPES = _READ_MCP_NODE_TYPES


def _projection_value(value: Any) -> Any:
    """Convert an allowlisted value into JSON-compatible public data."""

    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _projection_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return tuple(_projection_value(item) for item in value)
    return value


def _safe_projection(value: Any) -> tuple[dict[str, object], dict[str, str]] | None:
    """Build an explicit allowlist projection and category map for one node."""

    if isinstance(value, PersonAsset):
        node_type = NodeType.PERSON
        result = {"id": value.id, "name": value.name, "kind": value.kind.value, "status": value.status.value}
        category_prefix = "person"
    elif isinstance(value, Asset):
        node_type = NodeType.ASSET
        result = {"id": value.id, "name": value.name, "kind": value.kind.value, "description": value.description, "status": value.status.value}
        category_prefix = "asset"
    elif isinstance(value, Idea):
        node_type = NodeType.IDEA
        result = {"id": value.id, "title": value.title, "summary": value.summary, "description": value.description, "tags": value.tags, "status": value.status.value}
        category_prefix = "idea"
    elif isinstance(value, OwnerProfile):
        node_type = NodeType.OWNER_PROFILE
        result = {"id": value.id, "display_name": value.display_name, "status": value.status.value}
        category_prefix = "owner_profile"
    elif isinstance(value, Organization):
        node_type = NodeType.ORGANIZATION
        result = {"id": value.id, "name": value.name, "description": value.description, "status": value.status.value}
        category_prefix = "organization"
    elif isinstance(value, Source):
        node_type = NodeType.SOURCE
        result = {"id": value.id, "title": value.title, "kind": value.kind.value, "locator": value.locator, "current_revision_id": value.current_revision_id, "revision": value.revision, "status": value.status.value}
        category_prefix = "source"
    elif isinstance(value, SourceRevision):
        node_type = NodeType.SOURCE_REVISION
        result = {"id": value.id, "source_id": value.source_id, "revision": value.revision, "content": value.content, "locator": value.locator, "content_hash": value.content_hash, "retrieved_at": value.retrieved_at, "status": value.status.value}
        category_prefix = "source_revision"
    elif isinstance(value, ResearchMaterial):
        node_type = NodeType.RESEARCH_MATERIAL
        result = {"id": value.id, "title": value.title, "kind": value.kind.value, "locator": value.locator, "content_hash": value.content_hash, "content": value.content}
        category_prefix = "research_material"
    elif isinstance(value, Claim):
        node_type = NodeType.CLAIM
        result = {"id": value.id, "text": value.text, "claim_type": value.claim_type.value, "confidence": value.confidence, "evidence_ids": value.evidence_ids, "status": value.status.value, "revision": value.revision, "supersedes_id": value.supersedes_id}
        category_prefix = "claim"
    elif isinstance(value, Evidence):
        node_type = NodeType.EVIDENCE
        if value.content_chunk_id is not None:
            result = {"id": value.id, "polarity": value.polarity.value, "confidence": value.confidence, "content_hash": value.content_hash, "status": value.status.value}
        else:
            result = {"id": value.id, "material_id": value.material_id, "claim_id": value.claim_id, "source_revision_id": value.source_revision_id, "excerpt": value.excerpt, "locator": value.locator, "polarity": value.polarity.value, "confidence": value.confidence, "content_hash": value.content_hash, "status": value.status.value}
        category_prefix = "evidence"
    elif isinstance(value, ResearchCampaign):
        node_type = NodeType.RESEARCH_CAMPAIGN
        result = {"id": value.id, "purpose": value.purpose, "questions": value.questions, "target_idea_id": value.target_idea_id, "status": value.status.value}
        category_prefix = "research_campaign"
    elif isinstance(value, ResearchRun):
        node_type = NodeType.RESEARCH_RUN
        result = {"id": value.id, "campaign_id": value.campaign_id, "model_snapshot": value.model_snapshot, "sources": value.sources, "evidence_ids": value.evidence_ids, "status": value.status.value, "parent_run_id": value.parent_run_id, "supersedes_id": value.supersedes_id}
        category_prefix = "research_run"
    elif isinstance(value, ReportSection):
        node_type = NodeType.REPORT_SECTION
        result = {"id": int(value.id), "title": value.title, "content": value.content, "facts": value.facts, "ai_inferences": value.ai_inferences, "unconfirmed": value.unconfirmed, "owner_decisions": value.owner_decisions, "claim_ids": value.claim_ids, "evidence_ids": value.evidence_ids}
        category_prefix = "report_section"
    elif isinstance(value, ReportVersion):
        node_type = NodeType.REPORT_VERSION
        result = {"id": value.id, "sections": tuple(_safe_projection(section)[0] for section in value.sections), "parent_id": value.parent_id, "supersedes_id": value.supersedes_id, "change_reason": value.change_reason, "financial_formulas": value.financial_formulas, "decision_criteria": value.decision_criteria, "run_ids": value.run_ids, "evidence_ids": value.evidence_ids, "status": value.status.value}
        category_prefix = "report_version"
    elif isinstance(value, Decision):
        node_type = NodeType.DECISION
        result = {"id": value.id, "text": value.text, "claim_ids": value.claim_ids, "report_ids": value.report_ids, "experiment_ids": value.experiment_ids, "status": value.status.value}
        category_prefix = "decision"
    elif isinstance(value, Experiment):
        node_type = NodeType.EXPERIMENT
        result = {"id": value.id, "name": value.name, "success_criteria": value.success_criteria, "stop_criteria": value.stop_criteria, "status": value.status.value}
        category_prefix = "experiment"
    elif isinstance(value, InstructionArtifact):
        node_type = NodeType.INSTRUCTION_ARTIFACT
        result = {"id": value.id, "content_hash": value.content_hash, "status": value.status.value}
        category_prefix = "instruction_artifact"
    elif isinstance(value, EntityRevision):
        node_type = NodeType.ENTITY_REVISION
        result = {
            "id": value.id,
            "entity_id": value.entity_id,
            "entity_type": value.entity_type,
            "revision": value.revision,
            "payload_schema": value.payload_schema,
            "public_payload": value.public_payload,
            "content_hash": value.content_hash,
            "created_at": value.created_at,
            "provenance_id": value.provenance_id,
            "status": value.status.value,
        }
        category_prefix = "entity_revision"
    elif isinstance(value, RelationAssertion):
        node_type = NodeType.RELATION_ASSERTION
        result = {
            "id": value.id,
            "source_id": value.source_id,
            "target_id": value.target_id,
            "source_kind": value.source_kind,
            "target_kind": value.target_kind,
            "predicate": value.predicate,
            "assertion_family_id": value.assertion_family_id,
            "revision": value.revision,
            "status": value.status.value,
            "confidence": value.confidence,
            "evidence_ids": value.evidence_ids,
            "valid_from": value.valid_from,
            "expires_at": value.expires_at,
            "supersedes_id": value.supersedes_id,
            "provenance_id": value.provenance_id,
        }
        category_prefix = "relation_assertion"
    elif isinstance(value, ContentChunk):
        node_type = NodeType.CONTENT_CHUNK
        result = {
            "id": value.id,
            "source_revision_id": value.source_revision_id,
            "ordinal": value.ordinal,
            "char_start": value.char_start,
            "char_end": value.char_end,
            "text_hash": value.text_hash,
            "status": value.status.value,
        }
        category_prefix = "content_chunk"
    elif isinstance(value, Facet):
        node_type = NodeType.FACET
        result = {
            "id": value.id,
            "namespace": value.namespace,
            "normalized_value": value.normalized_value,
            "status": value.status.value,
        }
        category_prefix = "facet"
    else:
        return None

    allowlisted_fields = SHAREABLE_PROJECTION_ALLOWLIST[node_type]
    result = {key: _projection_value(result[key]) for key in allowlisted_fields if key in result}
    categories = {key: f"{category_prefix}.{key}" for key in result}
    return result, categories


def project_shareable(
    value: Any,
    authorization: CampaignAuthorizationSnapshot | None = None,
    *,
    authorization_snapshot: CampaignAuthorizationSnapshot | None = None,
    campaign: ResearchCampaign | None = None,
    authorization_registry: CampaignAuthorizationRegistry | None = None,
    registry: CampaignAuthorizationRegistry | None = None,
    current_context: CampaignAuthorizationRegistry | None = None,
    at: datetime | None = None,
) -> dict[str, object]:
    """Return a policy-aware projection built only from static allowlists."""

    if authorization is not None and authorization_snapshot is not None and authorization != authorization_snapshot:
        raise DomainValidationError("conflicting authorization snapshots")
    authorization = authorization_snapshot or authorization
    safe_projection = _safe_projection(value)
    if safe_projection is None:
        return {}
    result, categories = safe_projection
    policy = getattr(value, "egress_policy", EgressPolicy.LOCAL_ONLY)
    policy = _enum(policy, EgressPolicy, "egress_policy")
    explicit = policy is EgressPolicy.EXPLICIT
    if explicit:
        if not isinstance(authorization, CampaignAuthorizationSnapshot):
            raise DomainValidationError("explicit projection requires CampaignAuthorizationSnapshot")
        if campaign is None:
            raise DomainValidationError("explicit projection requires current campaign authorization")
        authorization = _validate_current_campaign_authorization(
            campaign,
            authorization,
            authorization_registry=authorization_registry,
            registry=registry,
            current_context=current_context,
            at=at,
        )
        authorization.validate(owner_id=value.owner_id, target_id=str(value.id), categories=(), at=at)
    elif policy is not EgressPolicy.SHAREABLE:
        return {}
    if not explicit:
        return result
    return {key: item for key, item in result.items() if authorization and authorization.allows_category(categories[key])}


shareable_projection = project_shareable
to_egress_projection = project_shareable


__all__ = [
    "Asset",
    "AssetKind",
    "AssetStatus",
    "CONTENT_CHUNK_MAX_LENGTH",
    "CONTENT_CHUNK_TARGET_LENGTH",
    "ContentChunk",
    "CampaignAuthorizationRegistry",
    "CampaignAuthorizationSnapshot",
    "CampaignStatus",
    "Claim",
    "ClaimKind",
    "ClaimStatus",
    "ClaimType",
    "DataPolicy",
    "DomainValidationError",
    "build_content_chunks",
    "deterministic_content_chunk_id",
    "EntityRevision",
    "EgressPolicy",
    "EntityStatus",
    "Evidence",
    "EvidencePolarity",
    "Facet",
    "Idea",
    "IdeaStatus",
    "Knowledge",
    "KnowledgeAsset",
    "MaterialKind",
    "NodeType",
    "now_utc",
    "new_id",
    "Person",
    "PersonAsset",
    "Provenance",
    "ProvenanceKind",
    "ProvenanceOrigin",
    "RelationStatus",
    "RelationAssertion",
    "RelationType",
    "Relationship",
    "RelationshipStatus",
    "RelationshipType",
    "ReportSection",
    "ReportSectionId",
    "ReportSectionID",
    "ReportVersion",
    "ReportStatus",
    "REPORT_SECTION_IDS",
    "REPORT_SECTION_NAMES",
    "REPORT_SECTION_TITLES",
    "REQUIRED_DECISION_CRITERIA_KEYS",
    "REQUIRED_FINANCIAL_FORMULA_KEYS",
    "ResearchCampaign",
    "ResearchMaterial",
    "ResearchMaterialKind",
    "ResearchRun",
    "READ_MCP_NODE_TYPES",
    "RunStatus",
    "Organization",
    "PROJECTION_ALLOWLIST",
    "SHAREABLE_PROJECTION_ALLOWLIST",
    "Source",
    "SourceRevision",
    "OwnerProfile",
    "Decision",
    "Experiment",
    "InstructionArtifact",
    "Status",
    "TransportRetry",
    "generate_id",
    "project_shareable",
    "report_section_title",
    "section_title",
    "shareable_projection",
    "split_source_content",
    "to_egress_projection",
    "validate_aggregate_references",
    "validate_campaign_reference",
    "validate_campaign_idea_reference",
    "validate_claim_reference",
    "validate_claim_evidence_references",
    "validate_evidence_reference",
    "validate_evidence_references",
    "validate_references",
    "validate_report_references",
    "validate_report_reference",
    "validate_run_reference",
    "validate_run_campaign_reference",
    "validate_source_history",
    "validate_source_revision_history",
    "validate_source_revisions",
    "utc_now",
]
