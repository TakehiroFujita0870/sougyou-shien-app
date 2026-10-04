"""Dependency-free enum vocabulary shared by Founder Graph domain adapters."""

from __future__ import annotations

from enum import StrEnum


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


EntityStatus = Status
IdeaStatus = Status
AssetStatus = Status
CampaignStatus = Status
RunStatus = Status
ClaimStatus = Status


class AssetKind(StrEnum):
    STRENGTH = "strength"
    KNOWLEDGE = "knowledge"
    PERSON = "person"
    EXPERIENCE = "experience"
    ARTIFACT = "artifact"
    DATA = "data"
    EQUIPMENT = "equipment"
    CHANNEL = "channel"
    ORGANIZATION = "organization"
    BARRIER = "barrier"


class AssetHomeCategory(StrEnum):
    """Screen grouping for an Asset, kept separate from its domain kind."""

    STRENGTH = "strength"
    BARRIER = "barrier"
    CRITERION = "criterion"


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
    RETRACTED = "retracted"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"


class RelationAssertionBasis(StrEnum):
    EXTERNAL_EVIDENCE = "external_evidence"
    BRIEF_HYPOTHESIS = "brief_hypothesis"


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


__all__ = [
    "AssetHomeCategory", "AssetKind", "AssetStatus", "CampaignStatus", "ClaimKind", "ClaimStatus", "ClaimType",
    "DataPolicy", "EgressPolicy", "EntityStatus", "EvidenceEdgeType", "EvidencePolarity",
    "IdeaStatus", "MaterialKind", "NodeType", "ProvenanceKind", "ProvenanceOrigin",
    "RelationAssertionEdgeType", "RelationStatus", "RelationType", "RelationshipStatus",
    "RelationshipType", "ReportStatus", "ResearchMaterialKind", "RunStatus", "Status",
]
