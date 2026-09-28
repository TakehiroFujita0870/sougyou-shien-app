"""Purpose-limited write MCP adapter for normal-chat write-back."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from hashlib import sha256
from typing import Any, Mapping
from urllib.parse import urlsplit

from .founder_graph import (
    Asset,
    AssetKind,
    Claim,
    Decision,
    DomainValidationError,
    EgressPolicy,
    EvidencePolarity,
    Idea,
    MaterialKind,
    NodeType,
    Organization,
    PersonAsset,
    Provenance,
    RelationAssertion,
    RelationAssertionBasis,
    RelationshipStatus,
    ReportSection,
    ReportStatus,
    ReportVersion,
    RelationType,
    Source,
    SourceRevision,
    Status,
)
from .founder_graph_mcp_annotations import mcp_tool_annotations
from .founder_graph_mcp_facets import (
    FACET_WRITE_TOOL_NAMES,
    dispatch_facet_write,
    facet_write_tool_definitions,
)
from .founder_graph_mcp_research import (
    McpResearchCampaignSurface,
    ResearchCampaignInputError,
    ResearchCampaignUnavailableError,
)
from .founder_graph_neo4j import Neo4jUnavailableError
from .founder_graph_write import (
    GraphWriteError,
    GraphWritePort,
    IdempotencyConflictError,
    RevisionConflictError,
    WriteReceipt,
)


class McpWriteError(Exception):
    """A safe, machine-readable write-surface error."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class McpWriteSurface:
    writes: GraphWritePort
    brief_store: Any | None = None
    candidate_processor: Any | None = None

    _TOOL_NAMES = (
        "capture_idea",
        "capture_source",
        "capture_person",
        "capture_organization",
        "capture_asset",
        "append_claim",
        "capture_evidence",
        "link_entities",
        "retract_relation_assertion",
        "record_decision",
        "record_correction",
        "confirm_person_merge",
    )
    _DESTRUCTIVE_TOOL_HINTS = {
        "capture_idea": False,
        "capture_source": False,
        "capture_person": False,
        "capture_organization": False,
        "capture_asset": False,
        "append_claim": False,
        "capture_evidence": False,
        "link_entities": False,
        "retract_relation_assertion": False,
        "record_decision": False,
        "record_correction": True,
        "confirm_person_merge": True,
    }

    def tool_definitions(self) -> tuple[Mapping[str, Any], ...]:
        text = {"type": "string"}
        ids = {"type": "array", "items": {"type": "string", "minLength": 1}}
        idempotency = {"type": "string", "minLength": 1, "description": "A stable key reused when the same request is retried."}
        schemas: dict[str, Mapping[str, Any]] = {
            "capture_source": {
                "type": "object",
                "description": "URLと自分で書いた短い要約をローカルに保存します。ページ取得や調査の許可にはなりません。",
                "required": ["url", "title", "summary", "idempotency_key"],
                "properties": {
                    "url": {"type": "string", "minLength": 1, "maxLength": 2048, "description": "HTTPまたはHTTPSの出典URL。ページ本文は取得しません。"},
                    "title": {"type": "string", "minLength": 1, "maxLength": 500, "description": "出典のタイトル。"},
                    "summary": {"type": "string", "minLength": 1, "maxLength": 4000, "description": "出典について自分で作成した1〜4000文字の要約。"},
                    "egress_policy": {"type": "string", "enum": [policy.value for policy in EgressPolicy], "description": "shareableは公開可能なURL・タイトル・短い要約に限り、明示指定が必要です。省略時はlocal_only。"},
                    "idempotency_key": idempotency,
                },
                "additionalProperties": False,
            },
            "capture_idea": {
                "type": "object",
                "description": "Save one founder idea. Use shareable only when the private MCP may return the text to ChatGPT.",
                "required": ["title", "idempotency_key"],
                "properties": {
                    "title": {**text, "minLength": 1},
                    "summary": text,
                    "description": text,
                    "source_text": {**text, "description": "The conversation or note that produced the idea."},
                    "tags": ids,
                    "egress_policy": {"type": "string", "enum": [policy.value for policy in EgressPolicy]},
                    "idempotency_key": idempotency,
                },
                "additionalProperties": False,
            },
            "capture_person": {
                "type": "object",
                "required": ["name", "idempotency_key"],
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "description": {"type": "string"},
                    "contact": {"type": "object", "additionalProperties": {"type": "string"}},
                    "private_notes": {"type": "string"},
                    "egress_policy": {"type": "string", "enum": [EgressPolicy.LOCAL_ONLY.value]},
                    "idempotency_key": {"type": "string", "minLength": 1},
                },
                "additionalProperties": False,
            },
            "capture_organization": {
                "type": "object",
                "required": ["name", "idempotency_key"],
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "description": {"type": "string"},
                    "egress_policy": {
                        "type": "string",
                        "enum": [policy.value for policy in EgressPolicy],
                    },
                    "idempotency_key": {"type": "string", "minLength": 1},
                },
                "additionalProperties": False,
            },
            "capture_asset": {
                "type": "object",
                "description": "強み・経験、または弱み・迷いの名称・種別・短い概要だけを保存します。弱み・迷いはkind=barrierです。本文、連絡先、個人メモ、出典本文、場所情報、来歴は受け付けません。",
                "required": ["name", "kind", "idempotency_key"],
                "properties": {
                    "name": {**text, "minLength": 1, "maxLength": 500},
                    "kind": {"type": "string", "enum": [kind.value for kind in AssetKind]},
                    "summary": {**text, "maxLength": 4000},
                    "egress_policy": {"type": "string", "enum": [EgressPolicy.LOCAL_ONLY.value, EgressPolicy.SHAREABLE.value]},
                    "idempotency_key": idempotency,
                },
                "additionalProperties": False,
            },
            "append_claim": {
                "type": "object",
                "required": ["text", "idempotency_key"],
                "properties": {
                    "text": {**text, "minLength": 1},
                    "claim_type": text,
                    "classification": text,
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "evidence_ids": ids,
                    "egress_policy": {
                        "type": "string",
                        "enum": [EgressPolicy.LOCAL_ONLY.value, EgressPolicy.SHAREABLE.value],
                    },
                    "idempotency_key": idempotency,
                },
                "additionalProperties": False,
            },
            "capture_evidence": {
                "type": "object",
                "description": "Attach a Claim to an already saved source chunk. Source text and excerpt are never accepted.",
                "required": ["claim_id", "content_chunk_id", "idempotency_key"],
                "properties": {
                    "claim_id": {**text, "minLength": 1},
                    "content_chunk_id": {**text, "minLength": 1},
                    "polarity": {"type": "string", "enum": [item.value for item in EvidencePolarity]},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "egress_policy": {"type": "string", "enum": [EgressPolicy.LOCAL_ONLY.value, EgressPolicy.SHAREABLE.value]},
                    "idempotency_key": idempotency,
                },
                "additionalProperties": False,
            },
            "link_entities": {
                "type": "object",
                "description": "外部事実にはsource-grounded Evidenceが必要です。brief_hypothesisはIdea Briefの内容から作る未確定な提案で、ownerが述べた事実とは区別し、EvidenceやResearchRunを作りません。",
                "required": ["source_id", "target_id", "relation", "idempotency_key"],
                "properties": {
                    "source_id": {**text, "minLength": 1},
                    "target_id": {**text, "minLength": 1},
                    "relation": {"type": "string", "enum": [relation.value for relation in RelationType]},
                    "basis": {"type": "string", "enum": [basis.value for basis in RelationAssertionBasis]},
                    "status": {"type": "string", "enum": [RelationshipStatus.PROPOSED.value, RelationshipStatus.INFERRED.value]},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "expires_at": {"type": "string", "description": "関係の期限を指定する場合のISO-8601日時。"},
                    "evidence_ids": ids,
                    "egress_policy": {
                        "type": "string",
                        "enum": [EgressPolicy.LOCAL_ONLY.value, EgressPolicy.SHAREABLE.value],
                    },
                    "based_on_brief_id": {**text, "minLength": 1},
                    "based_on_brief_section_index": {"type": "integer", "minimum": 0, "maximum": 7},
                    "supersedes_id": {**text, "minLength": 1, "description": "訂正する直近のRelationAssertion ID。既存の関係と同じfamilyを延長します。"},
                    "expected_family_revision": {"type": "integer", "minimum": 1, "description": "訂正対象familyの現在revision。楽観競合検出に使います。"},
                    "idempotency_key": idempotency,
                },
                "additionalProperties": False,
            },
            "retract_relation_assertion": {
                "type": "object",
                "description": "保存済みの未確定な関係を撤回します。外部事実の関係にはEvidenceが必要ですが、brief_hypothesisの撤回にはEvidenceを作りません。",
                "required": ["supersedes_id", "expected_family_revision", "idempotency_key"],
                "properties": {
                    "supersedes_id": {**text, "minLength": 1},
                    "expected_family_revision": {"type": "integer", "minimum": 1},
                    "evidence_ids": ids,
                    "egress_policy": {"type": "string", "enum": [policy.value for policy in EgressPolicy]},
                    "based_on_brief_id": {**text, "minLength": 1},
                    "based_on_brief_section_index": {"type": "integer", "minimum": 0, "maximum": 7},
                    "idempotency_key": idempotency,
                },
                "additionalProperties": False,
            },
            "record_decision": {
                "type": "object",
                "required": ["text", "idempotency_key"],
                "properties": {
                    "text": {**text, "minLength": 1},
                    "claim_ids": ids,
                    "report_ids": ids,
                    "experiment_ids": ids,
                    "status": {"type": "string", "enum": [status.value for status in Status]},
                    "idempotency_key": idempotency,
                },
                "additionalProperties": False,
            },
            "record_correction": {
                "type": "object",
                "required": ["previous_id", "idempotency_key"],
                "description": "Create a new revision while retaining the previous value.",
                "properties": {
                    "previous_id": {**text, "minLength": 1},
                    "text": text,
                    "title": text,
                    "summary": text,
                    "description": text,
                    "source_text": text,
                    "expected_revision": {"type": "integer", "minimum": 0},
                    "idempotency_key": idempotency,
                },
                "additionalProperties": False,
            },
            "confirm_person_merge": {
                "type": "object",
                "description": "Archive the losing local Person only after the owner explicitly confirms this namesake merge.",
                "required": ["winner_person_id", "loser_person_id", "confirmation", "evidence_ids", "idempotency_key"],
                "properties": {
                    "winner_person_id": {**text, "minLength": 1},
                    "loser_person_id": {**text, "minLength": 1},
                    "confirmation": {"type": "string", "enum": ["confirmed"]},
                    "evidence_ids": {**ids, "minItems": 1},
                    "idempotency_key": idempotency,
                },
                "additionalProperties": False,
            },
        }
        return tuple(
            {
                "name": name,
                "description": (
                    "Capture a local-only person contact without creating relationships."
                    if name == "capture_person"
                    else "Capture an organization node without creating relationships."
                    if name == "capture_organization"
                    else "資産の安全なメタデータのみを保存します。関係や添付本文は作成しません。"
                    if name == "capture_asset"
                    else "外部事実にはsource-grounded Evidenceが必要です。brief_hypothesisはIdea Briefに基づく未確定な提案で、ownerの明示的な主張とは区別します。"
                    if name == "link_entities"
                    else f"Purpose-limited Founder Graph write command: {name}. Provide the fields in the input schema and reuse idempotency_key on retries."
                ),
                "readOnly": False,
                "annotations": mcp_tool_annotations(
                    read_only=False,
                    destructive=self._DESTRUCTIVE_TOOL_HINTS[name],
                ),
                "inputSchema": schemas.get(name, {"type": "object", "additionalProperties": False}),
            }
            for name in self._TOOL_NAMES
        ) + McpResearchCampaignSurface(
            self.writes, self.brief_store, self.candidate_processor,
        ).tool_definitions() + facet_write_tool_definitions()

    def call(self, tool_name: str, arguments: Mapping[str, Any], *, owner_id: str) -> WriteReceipt:
        research_tools = {
            "create_research_campaign", "approve_research_campaign", "revoke_research_campaign",
            "record_research_run", "save_idea_brief", "append_research_finding", "save_researched_idea_brief",
        }
        if tool_name not in self._TOOL_NAMES and tool_name not in research_tools and tool_name not in FACET_WRITE_TOOL_NAMES:
            raise McpWriteError("unknown_tool", "Only the purpose-limited write tools are available.")
        if not isinstance(arguments, Mapping):
            raise McpWriteError("invalid_input", "Tool arguments must be an object.")
        if owner_id != self.writes.owner_id:
            raise McpWriteError("owner_mismatch", "The request owner is not the local owner.")
        try:
            if tool_name in FACET_WRITE_TOOL_NAMES:
                return dispatch_facet_write(self, tool_name, arguments)
            if tool_name in research_tools:
                return McpResearchCampaignSurface(
                    self.writes, self.brief_store, self.candidate_processor,
                ).call(
                    tool_name, arguments, owner_id=owner_id,
                )
            handler = getattr(self, f"_{tool_name}")
            return handler(arguments)
        except McpWriteError:
            raise
        except ResearchCampaignInputError as error:
            raise McpWriteError("invalid_input", str(error)) from error
        except ResearchCampaignUnavailableError as error:
            raise McpWriteError("unavailable", str(error)) from error
        except IdempotencyConflictError as error:
            raise McpWriteError("idempotency_conflict", str(error)) from error
        except RevisionConflictError as error:
            raise McpWriteError("revision_conflict", str(error)) from error
        except Neo4jUnavailableError as error:
            raise McpWriteError("unavailable", "The local Founder Graph is unavailable; retry after it starts.") from error
        except (DomainValidationError, GraphWriteError, ValueError, TypeError, KeyError) as error:
            raise McpWriteError("invalid_input", str(error)) from error

    def _capture_idea(self, arguments: Mapping[str, Any]) -> WriteReceipt:
        self._reject_unknown(arguments, {"title", "summary", "description", "source_text", "tags", "egress_policy", "idempotency_key"})
        idempotency_key = self._idempotency(arguments)
        idea_id = self._command_id("idea", idempotency_key)
        source_id = self._command_id("source", idempotency_key)
        source_revision_id = self._command_id("source-revision", idempotency_key)
        source_text = arguments.get("source_text", "")
        if not isinstance(source_text, str):
            raise McpWriteError("invalid_input", "source_text must be a string")
        source_provenance = Provenance(
            actor="local-owner",
            operation="capture_idea",
            target_id=source_id,
            source_id=source_revision_id,
            idempotency_key=f"{idempotency_key}:source",
        )
        source_revision_provenance = Provenance(
            actor="local-owner",
            operation="capture_idea",
            target_id=source_revision_id,
            source_id=source_revision_id,
            idempotency_key=f"{idempotency_key}:source-revision",
        )
        idea_provenance = Provenance(
            actor="local-owner",
            operation="capture_idea",
            target_id=idea_id,
            source_id=source_revision_id,
            idempotency_key=idempotency_key,
        )
        source_revision = SourceRevision(
            owner_id=self.writes.owner_id,
            id=source_revision_id,
            source_id=source_id,
            content=source_text,
            revision=1,
            egress_policy=EgressPolicy.LOCAL_ONLY,
            provenance=source_revision_provenance,
        )
        source = Source(
            owner_id=self.writes.owner_id,
            id=source_id,
            title=arguments.get("title", "Conversation source"),
            kind=MaterialKind.CONVERSATION,
            current_revision_id=source_revision_id,
            revision=1,
            egress_policy=EgressPolicy.LOCAL_ONLY,
            provenance=source_provenance,
        )
        idea = Idea(
            owner_id=self.writes.owner_id,
            id=idea_id,
            title=arguments.get("title", ""),
            summary=arguments.get("summary", ""),
            description=arguments.get("description", ""),
            source_text="",
            tags=arguments.get("tags", ()),
            egress_policy=EgressPolicy(arguments.get("egress_policy", EgressPolicy.LOCAL_ONLY)),
            provenance=idea_provenance,
        )
        return self.writes.capture_idea(
            idea,
            source,
            source_revision,
            idempotency_key=idempotency_key,
        )

    def _capture_source(self, arguments: Mapping[str, Any]) -> WriteReceipt:
        self._reject_unknown(arguments, {"url", "title", "summary", "egress_policy", "idempotency_key"})
        idempotency_key = self._idempotency(arguments)
        url = self._text(arguments.get("url"), "url", max_length=2048)
        title = self._text(arguments.get("title"), "title", max_length=500)
        summary = self._text(arguments.get("summary"), "summary", max_length=4000)
        try:
            egress_policy = EgressPolicy(arguments.get("egress_policy", EgressPolicy.LOCAL_ONLY.value))
        except (TypeError, ValueError) as error:
            raise McpWriteError("invalid_input", "egress_policy must be local_only or shareable") from error
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise McpWriteError("invalid_input", "url must be an absolute HTTP(S) URL without credentials")
        source_id = self._command_id("source", idempotency_key)
        revision_id = self._command_id("source-revision", idempotency_key)
        provenance = Provenance(actor="local-owner", operation="capture_source", target_id=source_id,
            source_id=revision_id, idempotency_key=f"{idempotency_key}:source")
        revision_provenance = replace(provenance, target_id=revision_id, idempotency_key=f"{idempotency_key}:source-revision")
        revision = SourceRevision(owner_id=self.writes.owner_id, id=revision_id, source_id=source_id,
            content=summary, locator=url, revision=1, egress_policy=egress_policy,
            provenance=revision_provenance)
        source = Source(owner_id=self.writes.owner_id, id=source_id, title=title, kind=MaterialKind.WEB,
            locator=url, current_revision_id=revision_id, revision=1,
            egress_policy=egress_policy, provenance=provenance)
        return self.writes.capture_source(source, revision, idempotency_key=idempotency_key)

    def _capture_person(self, arguments: Mapping[str, Any]) -> WriteReceipt:
        self._reject_unknown(
            arguments,
            {"name", "description", "contact", "private_notes", "egress_policy", "idempotency_key"},
        )
        idempotency_key = self._idempotency(arguments)
        requested_policy = EgressPolicy(arguments.get("egress_policy", EgressPolicy.LOCAL_ONLY))
        if requested_policy is not EgressPolicy.LOCAL_ONLY:
            raise McpWriteError("invalid_input", "capture_person requires local_only egress_policy.")
        contact = self._contact(arguments.get("contact", {}))
        person = PersonAsset(
            owner_id=self.writes.owner_id,
            id=self._command_id("person", idempotency_key),
            name=self._text(arguments.get("name"), "name"),
            description=arguments.get("description", ""),
            contact=contact,
            private_notes=arguments.get("private_notes", ""),
            egress_policy=EgressPolicy.LOCAL_ONLY,
            provenance=Provenance(
                actor="local-owner",
                operation="capture_person",
                target_id=self._command_id("person", idempotency_key),
                idempotency_key=idempotency_key,
            ),
        )
        return self.writes.put_node(person, idempotency_key=idempotency_key, operation="capture_person")

    def _capture_organization(self, arguments: Mapping[str, Any]) -> WriteReceipt:
        self._reject_unknown(arguments, {"name", "description", "egress_policy", "idempotency_key"})
        idempotency_key = self._idempotency(arguments)
        organization_id = self._command_id("organization", idempotency_key)
        organization = Organization(
            owner_id=self.writes.owner_id,
            id=organization_id,
            name=self._text(arguments.get("name"), "name"),
            description=arguments.get("description", ""),
            egress_policy=EgressPolicy(arguments.get("egress_policy", EgressPolicy.LOCAL_ONLY)),
            provenance=Provenance(
                actor="local-owner",
                operation="capture_organization",
                target_id=organization_id,
                idempotency_key=idempotency_key,
            ),
        )
        return self.writes.put_node(
            organization,
            idempotency_key=idempotency_key,
            operation="capture_organization",
        )

    def _capture_asset(self, arguments: Mapping[str, Any]) -> WriteReceipt:
        self._reject_unknown(arguments, {"name", "kind", "summary", "egress_policy", "idempotency_key"})
        idempotency_key = self._idempotency(arguments)
        try:
            policy = EgressPolicy(arguments.get("egress_policy", EgressPolicy.LOCAL_ONLY))
            kind = AssetKind(arguments.get("kind"))
        except (TypeError, ValueError) as error:
            raise McpWriteError("invalid_input", "kind must be supported and egress_policy must be local_only or shareable.") from error
        if policy not in {EgressPolicy.LOCAL_ONLY, EgressPolicy.SHAREABLE}:
            raise McpWriteError("invalid_input", "capture_asset allows only local_only or shareable.")
        summary = arguments.get("summary", "")
        if not isinstance(summary, str) or len(summary) > 4000:
            raise McpWriteError("invalid_input", "summary must be a string of at most 4000 characters")
        asset_id = self._command_id("asset", idempotency_key)
        asset = Asset(
            owner_id=self.writes.owner_id,
            id=asset_id,
            name=self._text(arguments.get("name"), "name", max_length=500),
            kind=kind,
            description=summary.strip(),
            details={},
            egress_policy=policy,
            provenance=Provenance(actor="local-owner", operation="capture_asset", target_id=asset_id, idempotency_key=idempotency_key),
        )
        return self.writes.put_node(asset, idempotency_key=idempotency_key, operation="capture_asset")

    def _append_claim(self, arguments: Mapping[str, Any]) -> WriteReceipt:
        self._reject_unknown(arguments, {"text", "claim_type", "classification", "confidence", "evidence_ids", "egress_policy", "idempotency_key"})
        try:
            egress_policy = EgressPolicy(arguments.get("egress_policy", EgressPolicy.LOCAL_ONLY))
        except (TypeError, ValueError) as error:
            raise McpWriteError("invalid_input", "append_claim allows only local_only or shareable.") from error
        if egress_policy not in {EgressPolicy.LOCAL_ONLY, EgressPolicy.SHAREABLE}:
            raise McpWriteError("invalid_input", "append_claim allows only local_only or shareable.")
        claim = Claim(
            owner_id=self.writes.owner_id,
            id=self._command_id("claim", self._idempotency(arguments)),
            text=arguments.get("text", ""),
            claim_type=arguments.get("claim_type", "fact"),
            classification=arguments.get("classification"),
            confidence=arguments.get("confidence", 0.0),
            evidence_ids=arguments.get("evidence_ids", ()),
            egress_policy=egress_policy,
        )
        return self.writes.put_node(claim, idempotency_key=self._idempotency(arguments), operation="append_claim")

    def _capture_evidence(self, arguments: Mapping[str, Any]) -> WriteReceipt:
        self._reject_unknown(arguments, {"claim_id", "content_chunk_id", "polarity", "confidence", "egress_policy", "idempotency_key"})
        try:
            egress_policy = EgressPolicy(arguments.get("egress_policy", EgressPolicy.LOCAL_ONLY.value))
        except (TypeError, ValueError) as error:
            raise McpWriteError("invalid_input", "egress_policy must be local_only or shareable.") from error
        capture = getattr(self.writes, "capture_evidence", None)
        if not callable(capture):
            raise McpWriteError("unavailable", "Source-grounded evidence writes are not available on this graph adapter.")
        try:
            polarity = EvidencePolarity(arguments.get("polarity", EvidencePolarity.SUPPORTS.value))
        except (TypeError, ValueError) as error:
            raise McpWriteError("invalid_input", "polarity must be supports, contradicts, or neutral.") from error
        return capture(
            self._text(arguments.get("claim_id"), "claim_id"),
            self._text(arguments.get("content_chunk_id"), "content_chunk_id"),
            polarity=polarity,
            confidence=arguments.get("confidence", 1.0),
            egress_policy=egress_policy,
            idempotency_key=self._idempotency(arguments),
        )

    def _link_entities(self, arguments: Mapping[str, Any]) -> WriteReceipt:
        self._reject_unknown(arguments, {
            "source_id", "target_id", "relation", "status", "basis", "confidence", "expires_at", "evidence_ids",
            "egress_policy", "based_on_brief_id", "based_on_brief_section_index", "supersedes_id",
            "expected_family_revision", "idempotency_key",
        })
        save_assertion = getattr(self.writes, "save_relation_assertion", None)
        if not callable(save_assertion):
            raise McpWriteError("unavailable", "Formal relation writes are not available on this graph adapter.")
        source_id = self._text(arguments.get("source_id"), "source_id")
        target_id = self._text(arguments.get("target_id"), "target_id")
        source = self.writes.get_node(source_id)
        target = self.writes.get_node(target_id)
        if source is None or target is None:
            raise McpWriteError("not_found", "relation endpoints must already exist")
        if getattr(source, "owner_id", None) != self.writes.owner_id or getattr(target, "owner_id", None) != self.writes.owner_id:
            raise McpWriteError("not_found", "relation endpoints must already exist")
        try:
            source_kind = NodeType(source.node_type)
            target_kind = NodeType(target.node_type)
            predicate = RelationType(arguments.get("relation"))
            status = RelationshipStatus(arguments.get("status", RelationshipStatus.PROPOSED.value))
            basis = RelationAssertionBasis(arguments.get("basis", RelationAssertionBasis.EXTERNAL_EVIDENCE.value))
            egress_policy = EgressPolicy(arguments.get("egress_policy", EgressPolicy.LOCAL_ONLY.value))
        except (AttributeError, TypeError, ValueError) as error:
            raise McpWriteError("invalid_input", "Relation type, basis, status, or egress policy is invalid.") from error
        if status not in {RelationshipStatus.PROPOSED, RelationshipStatus.INFERRED}:
            raise McpWriteError("invalid_input", "Model-generated relations may only be proposed or inferred.")
        if egress_policy not in {EgressPolicy.LOCAL_ONLY, EgressPolicy.SHAREABLE}:
            raise McpWriteError("invalid_input", "Relation egress policy must be local_only or shareable.")
        brief_id = arguments.get("based_on_brief_id")
        section_index = arguments.get("based_on_brief_section_index")
        has_idea_endpoint = source_kind is NodeType.IDEA or target_kind is NodeType.IDEA
        if has_idea_endpoint:
            whole_draft_hypothesis = basis is RelationAssertionBasis.BRIEF_HYPOTHESIS
            if not whole_draft_hypothesis and (brief_id is None) != (section_index is None):
                raise McpWriteError("invalid_input", "Idea relations require both Brief reference fields.")
            if whole_draft_hypothesis and brief_id is None:
                raise McpWriteError("invalid_input", "Brief hypotheses require a latest Brief reference.")
            if brief_id is not None:
                brief_id = self._text(brief_id, "based_on_brief_id")
            if section_index is not None and (type(section_index) is not int or not 0 <= section_index <= 7):
                raise McpWriteError("invalid_input", "Idea relations require a Brief section index from 0 to 7.")
        elif brief_id is not None or section_index is not None:
            raise McpWriteError("invalid_input", "Brief references are accepted only for relations with an Idea endpoint.")
        evidence_ids = self._ids(arguments.get("evidence_ids", ()), "evidence_ids")
        expires_at = arguments.get("expires_at")
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        elif expires_at is not None and not isinstance(expires_at, datetime):
            raise McpWriteError("invalid_input", "expires_at must be an ISO-8601 timestamp string.")
        idempotency_key = self._idempotency(arguments)
        assertion_id = self._command_id("relation-assertion", idempotency_key)
        supersedes_id = arguments.get("supersedes_id")
        expected_family_revision = arguments.get("expected_family_revision")
        predecessor = None
        if supersedes_id is None:
            if expected_family_revision is not None:
                raise McpWriteError("invalid_input", "expected_family_revision requires supersedes_id")
            family_id = self._command_id("relation-family", idempotency_key)
            revision = 1
        else:
            supersedes_id = self._text(supersedes_id, "supersedes_id")
            if type(expected_family_revision) is not int or expected_family_revision < 1:
                raise McpWriteError("invalid_input", "a positive expected_family_revision is required with supersedes_id")
            predecessor = self.writes.get_node(supersedes_id)
            if not isinstance(predecessor, RelationAssertion) or predecessor.owner_id != self.writes.owner_id:
                raise McpWriteError("not_found", "the relation to correct does not exist")
            if predecessor.status is RelationshipStatus.CONFIRMED:
                raise McpWriteError("invalid_input", "confirmed relation assertions cannot be corrected by this tool")
            if predecessor.revision != expected_family_revision:
                raise RevisionConflictError("expected relation family revision is stale")
            if "basis" not in arguments:
                basis = predecessor.basis
            if (predecessor.source_id, predecessor.target_id, predecessor.predicate) != (source_id, target_id, predicate):
                raise McpWriteError("invalid_input", "a relation correction must retain its endpoints and predicate")
            family_id = predecessor.assertion_family_id
            revision = predecessor.revision + 1
            if arguments.get("egress_policy") is None:
                egress_policy = predecessor.egress_policy
            if status not in {RelationshipStatus.PROPOSED, RelationshipStatus.INFERRED}:
                raise McpWriteError("invalid_input", "Model-generated relations may only be proposed or inferred.")
            if brief_id is None and has_idea_endpoint:
                brief_id = predecessor.based_on_brief_id
                section_index = predecessor.based_on_brief_section_index
            if "confidence" not in arguments:
                confidence = predecessor.confidence
            else:
                confidence = arguments.get("confidence")
            if "expires_at" not in arguments:
                expires_at = predecessor.expires_at
        if supersedes_id is None:
            if has_idea_endpoint and brief_id is None:
                raise McpWriteError("invalid_input", "New Idea relations require a Brief reference; external-evidence relations also require its section index.")
            if has_idea_endpoint and basis is not RelationAssertionBasis.BRIEF_HYPOTHESIS and section_index is None:
                raise McpWriteError("invalid_input", "External-evidence Idea relations require a Brief section index.")
            confidence = arguments.get("confidence")
        assertion = RelationAssertion(
            owner_id=self.writes.owner_id,
            id=assertion_id,
            source_id=source_id,
            source_kind=source_kind,
            target_id=target_id,
            target_kind=target_kind,
            predicate=predicate,
            assertion_family_id=family_id,
            revision=revision,
            status=status,
            basis=basis,
            confidence=confidence,
            expires_at=expires_at,
            supersedes_id=supersedes_id,
            evidence_ids=evidence_ids,
            egress_policy=egress_policy,
            based_on_brief_id=brief_id,
            based_on_brief_section_index=section_index,
            provenance=Provenance(
                actor="local-owner",
                operation="link_entities",
                target_id=assertion_id,
                idempotency_key=idempotency_key,
            ),
        )
        existing = self.writes.get_node(assertion_id)
        if isinstance(existing, RelationAssertion) and existing.owner_id == self.writes.owner_id:
            replay_candidate = replace(
                existing,
                valid_from=assertion.valid_from,
                provenance=replace(existing.provenance, occurred_at=assertion.provenance.occurred_at),
            )
            if replay_candidate == assertion:
                assertion = existing
        return save_assertion(
            assertion,
            expected_family_revision=expected_family_revision,
            idempotency_key=idempotency_key,
        )

    def _retract_relation_assertion(self, arguments: Mapping[str, Any]) -> WriteReceipt:
        self._reject_unknown(arguments, {
            "supersedes_id", "expected_family_revision", "evidence_ids", "egress_policy",
            "based_on_brief_id", "based_on_brief_section_index", "idempotency_key",
        })
        save_assertion = getattr(self.writes, "save_relation_assertion", None)
        if not callable(save_assertion):
            raise McpWriteError("unavailable", "Formal relation writes are not available on this graph adapter.")
        predecessor_id = self._text(arguments.get("supersedes_id"), "supersedes_id")
        predecessor = self.writes.get_node(predecessor_id)
        if not isinstance(predecessor, RelationAssertion) or predecessor.owner_id != self.writes.owner_id:
            raise McpWriteError("not_found", "the relation to retract does not exist")
        if predecessor.status is RelationshipStatus.CONFIRMED:
            raise McpWriteError("invalid_input", "confirmed relation assertions cannot be retracted by this tool")
        expected = arguments.get("expected_family_revision")
        if type(expected) is not int or expected < 1:
            raise McpWriteError("invalid_input", "a positive expected_family_revision is required")
        if predecessor.revision != expected:
            raise RevisionConflictError("expected relation family revision is stale")
        evidence_ids = self._ids(arguments.get("evidence_ids", ()), "evidence_ids")
        if predecessor.basis is RelationAssertionBasis.BRIEF_HYPOTHESIS and evidence_ids:
            raise McpWriteError("invalid_input", "Brief hypothesis retraction cannot claim external Evidence")
        if predecessor.basis is not RelationAssertionBasis.BRIEF_HYPOTHESIS and not evidence_ids:
            raise McpWriteError("invalid_input", "retraction requires at least one evidence id")
        try:
            policy = EgressPolicy(arguments.get("egress_policy", predecessor.egress_policy.value))
        except (TypeError, ValueError) as error:
            raise McpWriteError("invalid_input", "egress_policy must be local_only or shareable") from error
        brief_id = arguments.get("based_on_brief_id", predecessor.based_on_brief_id)
        section_index = arguments.get("based_on_brief_section_index", predecessor.based_on_brief_section_index)
        idempotency_key = self._idempotency(arguments)
        assertion_id = self._command_id("relation-assertion", idempotency_key)
        assertion = replace(
            predecessor,
            id=assertion_id,
            revision=predecessor.revision + 1,
            status=RelationshipStatus.RETRACTED,
            evidence_ids=evidence_ids,
            valid_from=datetime.now(predecessor.valid_from.tzinfo),
            expires_at=None,
            supersedes_id=predecessor.id,
            egress_policy=policy,
            based_on_brief_id=brief_id,
            based_on_brief_section_index=section_index,
            provenance=Provenance(actor="local-owner", operation="retract_relation_assertion", target_id=assertion_id, idempotency_key=idempotency_key),
            provenance_id=None,
        )
        existing = self.writes.get_node(assertion_id)
        if isinstance(existing, RelationAssertion) and existing.owner_id == self.writes.owner_id:
            replay_candidate = replace(
                existing,
                valid_from=assertion.valid_from,
                provenance=replace(existing.provenance, occurred_at=assertion.provenance.occurred_at),
            )
            if replay_candidate == assertion:
                assertion = existing
        return save_assertion(
            assertion,
            expected_family_revision=expected,
            idempotency_key=idempotency_key,
        )

    def _confirm_person_merge(self, arguments: Mapping[str, Any]) -> WriteReceipt:
        self._reject_unknown(arguments, {"winner_person_id", "loser_person_id", "confirmation", "evidence_ids", "idempotency_key"})
        winner_id = self._text(arguments.get("winner_person_id"), "winner_person_id")
        loser_id = self._text(arguments.get("loser_person_id"), "loser_person_id")
        if winner_id == loser_id:
            raise McpWriteError("invalid_input", "winner_person_id and loser_person_id must be different")
        if arguments.get("confirmation") != "confirmed":
            raise McpWriteError("invalid_input", "person merge requires explicit confirmation=confirmed")
        evidence_ids = self._ids(arguments.get("evidence_ids"), "evidence_ids")
        if not evidence_ids:
            raise McpWriteError("invalid_input", "person merge requires at least one confirmation evidence id")
        winner = self.writes.get_node(winner_id)
        loser = self.writes.get_node(loser_id)
        if not isinstance(winner, PersonAsset) or not isinstance(loser, PersonAsset):
            raise McpWriteError("invalid_input", "person merge endpoints must be saved Person records")
        idempotency_key = self._idempotency(arguments)
        assertion_id = self._command_id("relation-assertion", idempotency_key)
        assertion = RelationAssertion(
            owner_id=self.writes.owner_id,
            id=assertion_id,
            source_id=loser.id,
            source_kind=loser.node_type,
            target_id=winner.id,
            target_kind=winner.node_type,
            predicate=RelationType.MERGED_INTO,
            assertion_family_id=self._command_id("merge-family", idempotency_key),
            status="confirmed",
            evidence_ids=evidence_ids,
            provenance=Provenance(
                actor="local-owner",
                operation="confirm_person_merge",
                target_id=assertion_id,
                idempotency_key=idempotency_key,
            ),
        )
        return self.writes.confirm_person_merge(assertion, idempotency_key=idempotency_key)

    def _save_research_report(self, arguments: Mapping[str, Any]) -> WriteReceipt:
        self._reject_unknown(arguments, {"sections", "run_ids", "evidence_ids", "financial_formulas", "decision_criteria", "status", "parent_id", "change_reason", "idempotency_key"})
        raw_sections = arguments.get("sections")
        if not isinstance(raw_sections, (list, tuple)):
            raise McpWriteError("invalid_input", "sections must be an array")
        sections = tuple(
            ReportSection(
                owner_id=self.writes.owner_id,
                id=item.get("id"),
                content=item.get("content", ""),
                facts=item.get("facts", ()),
                ai_inferences=item.get("ai_inferences", ()),
                unconfirmed=item.get("unconfirmed", ()),
                owner_decisions=item.get("owner_decisions", ()),
                claim_ids=item.get("claim_ids", ()),
                evidence_ids=item.get("evidence_ids", ()),
            )
            for item in raw_sections
            if isinstance(item, Mapping)
        )
        report = ReportVersion(
            owner_id=self.writes.owner_id,
            id=self._command_id("report", self._idempotency(arguments)),
            sections=sections,
            run_ids=arguments.get("run_ids", ()),
            evidence_ids=arguments.get("evidence_ids", ()),
            financial_formulas=arguments.get("financial_formulas", {}),
            decision_criteria=arguments.get("decision_criteria", {}),
            status=ReportStatus(arguments.get("status", ReportStatus.DRAFT)),
            parent_id=arguments.get("parent_id"),
            change_reason=arguments.get("change_reason", "initial"),
        )
        return self.writes.put_node(report, idempotency_key=self._idempotency(arguments), operation="save_research_report")

    def _record_decision(self, arguments: Mapping[str, Any]) -> WriteReceipt:
        self._reject_unknown(arguments, {"text", "claim_ids", "report_ids", "experiment_ids", "status", "idempotency_key"})
        decision = Decision(
            owner_id=self.writes.owner_id,
            id=self._command_id("decision", self._idempotency(arguments)),
            text=arguments.get("text", ""),
            claim_ids=arguments.get("claim_ids", ()),
            report_ids=arguments.get("report_ids", ()),
            experiment_ids=arguments.get("experiment_ids", ()),
            status=arguments.get("status", Status.ACTIVE),
        )
        return self.writes.put_node(decision, idempotency_key=self._idempotency(arguments), operation="record_decision")

    def _record_correction(self, arguments: Mapping[str, Any]) -> WriteReceipt:
        self._reject_unknown(arguments, {"previous_id", "text", "title", "summary", "description", "source_text", "idempotency_key", "expected_revision"})
        previous_id = self._text(arguments.get("previous_id"), "previous_id")
        previous = self.writes.get_node(previous_id)
        if previous is None:
            raise McpWriteError("not_found", "the previous node does not exist")
        if isinstance(previous, Idea):
            replacement = previous.revise(
                title=arguments.get("title"),
                summary=arguments.get("summary"),
                description=arguments.get("description"),
                source_text=arguments.get("source_text"),
            )
        elif isinstance(previous, Claim):
            replacement = previous.revise(text=self._text(arguments.get("text"), "text"))
        else:
            raise McpWriteError("unsupported_correction", "Only Idea and Claim corrections are supported by this command.")
        replacement_id = self._command_id(
            "idea" if isinstance(replacement, Idea) else "claim",
            self._idempotency(arguments),
        )
        replacement = replace(
            replacement,
            id=replacement_id,
            provenance=replace(replacement.provenance, target_id=replacement_id),
        )
        return self.writes.record_correction(
            previous_id,
            replacement,
            idempotency_key=self._idempotency(arguments),
            expected_revision=arguments.get("expected_revision"),
        )

    @staticmethod
    def _idempotency(arguments: Mapping[str, Any]) -> str:
        return McpWriteSurface._text(arguments.get("idempotency_key"), "idempotency_key")

    @staticmethod
    def _command_id(prefix: str, idempotency_key: str) -> str:
        return f"{prefix}_{sha256(idempotency_key.encode('utf-8')).hexdigest()[:32]}"

    @staticmethod
    def _text(value: Any, field_name: str, *, max_length: int | None = None) -> str:
        if not isinstance(value, str) or not value.strip():
            raise McpWriteError("invalid_input", f"{field_name} must be a non-empty string")
        normalized = value.strip()
        if max_length is not None and len(normalized) > max_length:
            raise McpWriteError("invalid_input", f"{field_name} exceeds the allowed length")
        return normalized

    @staticmethod
    def _ids(value: Any, field_name: str) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)):
            raise McpWriteError("invalid_input", f"{field_name} must be an array of non-empty strings")
        values = tuple(McpWriteSurface._text(item, field_name) for item in value)
        if len(set(values)) != len(values):
            raise McpWriteError("invalid_input", f"{field_name} must not contain duplicates")
        return values

    @staticmethod
    def _contact(value: Any) -> dict[str, str]:
        if not isinstance(value, Mapping):
            raise McpWriteError("invalid_input", "contact must be an object of string values.")
        contact: dict[str, str] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key.strip() or not isinstance(item, str):
                raise McpWriteError("invalid_input", "contact must be an object of string values.")
            contact[key.strip()] = item
        return contact

    @staticmethod
    def _reject_unknown(arguments: Mapping[str, Any], allowed: set[str]) -> None:
        if set(arguments).difference(allowed):
            raise McpWriteError("invalid_input", "Unknown tool arguments are not accepted.")
