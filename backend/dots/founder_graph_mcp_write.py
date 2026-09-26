"""Purpose-limited write MCP adapter for normal-chat write-back."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from hashlib import sha256
from typing import Any, Mapping
from urllib.parse import urlsplit

from .founder_graph import (
    Claim,
    Decision,
    DomainValidationError,
    EgressPolicy,
    Idea,
    MaterialKind,
    NodeType,
    Organization,
    PersonAsset,
    Provenance,
    RelationAssertion,
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

    _TOOL_NAMES = (
        "capture_idea",
        "capture_source",
        "capture_person",
        "capture_organization",
        "append_claim",
        "link_entities",
        "save_research_report",
        "record_decision",
        "record_correction",
        "confirm_person_merge",
    )
    _DESTRUCTIVE_TOOL_HINTS = {
        "capture_idea": False,
        "capture_source": False,
        "capture_person": False,
        "capture_organization": False,
        "append_claim": False,
        "link_entities": False,
        "save_research_report": False,
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
            "link_entities": {
                "type": "object",
                "description": "保存済みの記録同士を、根拠付きの未確定な関係として結びます。Ideaを含む場合は、調査済みBriefの章とEvidenceが必要です。",
                "required": ["source_id", "target_id", "relation", "evidence_ids", "idempotency_key"],
                "properties": {
                    "source_id": {**text, "minLength": 1},
                    "target_id": {**text, "minLength": 1},
                    "relation": {"type": "string", "enum": [relation.value for relation in RelationType]},
                    "status": {"type": "string", "enum": [RelationshipStatus.PROPOSED.value, RelationshipStatus.INFERRED.value]},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "expires_at": {"type": "string", "description": "関係の期限を指定する場合のISO-8601日時。"},
                    "evidence_ids": {**ids, "minItems": 1},
                    "egress_policy": {
                        "type": "string",
                        "enum": [EgressPolicy.LOCAL_ONLY.value, EgressPolicy.SHAREABLE.value],
                    },
                    "based_on_brief_id": {**text, "minLength": 1},
                    "based_on_brief_section_index": {"type": "integer", "minimum": 0, "maximum": 7},
                    "idempotency_key": idempotency,
                },
                "additionalProperties": False,
            },
            "save_research_report": {
                "type": "object",
                "required": ["sections", "idempotency_key"],
                "properties": {
                    "sections": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["content"],
                            "properties": {
                                "id": text,
                                "content": {**text, "minLength": 1},
                                "facts": ids,
                                "ai_inferences": ids,
                                "unconfirmed": ids,
                                "owner_decisions": ids,
                                "claim_ids": ids,
                                "evidence_ids": ids,
                            },
                            "additionalProperties": False,
                        },
                    },
                    "run_ids": ids,
                    "evidence_ids": ids,
                    "financial_formulas": {"type": "object", "additionalProperties": True},
                    "decision_criteria": {"type": "object", "additionalProperties": True},
                    "status": {"type": "string", "enum": [status.value for status in ReportStatus]},
                    "parent_id": text,
                    "change_reason": text,
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
                    else "保存済みの記録同士を、根拠付きの未確定な関係として結びます。Ideaを含む場合は、調査済みBriefの章とEvidenceが必要です。"
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
        )

    def call(self, tool_name: str, arguments: Mapping[str, Any], *, owner_id: str) -> WriteReceipt:
        if tool_name not in self._TOOL_NAMES:
            raise McpWriteError("unknown_tool", "Only the purpose-limited write tools are available.")
        if not isinstance(arguments, Mapping):
            raise McpWriteError("invalid_input", "Tool arguments must be an object.")
        if owner_id != self.writes.owner_id:
            raise McpWriteError("owner_mismatch", "The request owner is not the local owner.")
        try:
            handler = getattr(self, f"_{tool_name}")
            return handler(arguments)
        except McpWriteError:
            raise
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
        self._reject_unknown(arguments, {"url", "title", "summary", "idempotency_key"})
        idempotency_key = self._idempotency(arguments)
        url = self._text(arguments.get("url"), "url", max_length=2048)
        title = self._text(arguments.get("title"), "title", max_length=500)
        summary = self._text(arguments.get("summary"), "summary", max_length=4000)
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise McpWriteError("invalid_input", "url must be an absolute HTTP(S) URL without credentials")
        source_id = self._command_id("source", idempotency_key)
        revision_id = self._command_id("source-revision", idempotency_key)
        provenance = Provenance(actor="local-owner", operation="capture_source", target_id=source_id,
            source_id=revision_id, idempotency_key=f"{idempotency_key}:source")
        revision_provenance = replace(provenance, target_id=revision_id, idempotency_key=f"{idempotency_key}:source-revision")
        revision = SourceRevision(owner_id=self.writes.owner_id, id=revision_id, source_id=source_id,
            content=summary, locator=url, revision=1, egress_policy=EgressPolicy.LOCAL_ONLY,
            provenance=revision_provenance)
        source = Source(owner_id=self.writes.owner_id, id=source_id, title=title, kind=MaterialKind.WEB,
            locator=url, current_revision_id=revision_id, revision=1,
            egress_policy=EgressPolicy.LOCAL_ONLY, provenance=provenance)
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
        )
        return self.writes.put_node(person, idempotency_key=idempotency_key, operation="capture_person")

    def _capture_organization(self, arguments: Mapping[str, Any]) -> WriteReceipt:
        self._reject_unknown(arguments, {"name", "description", "egress_policy", "idempotency_key"})
        idempotency_key = self._idempotency(arguments)
        organization = Organization(
            owner_id=self.writes.owner_id,
            id=self._command_id("organization", idempotency_key),
            name=self._text(arguments.get("name"), "name"),
            description=arguments.get("description", ""),
            egress_policy=EgressPolicy(arguments.get("egress_policy", EgressPolicy.LOCAL_ONLY)),
        )
        return self.writes.put_node(
            organization,
            idempotency_key=idempotency_key,
            operation="capture_organization",
        )

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

    def _link_entities(self, arguments: Mapping[str, Any]) -> WriteReceipt:
        self._reject_unknown(arguments, {
            "source_id", "target_id", "relation", "status", "confidence", "expires_at", "evidence_ids",
            "egress_policy", "based_on_brief_id", "based_on_brief_section_index", "idempotency_key",
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
            egress_policy = EgressPolicy(arguments.get("egress_policy", EgressPolicy.LOCAL_ONLY.value))
        except (AttributeError, TypeError, ValueError) as error:
            raise McpWriteError("invalid_input", "Relation type, status, or egress policy is invalid.") from error
        if status not in {RelationshipStatus.PROPOSED, RelationshipStatus.INFERRED}:
            raise McpWriteError("invalid_input", "Model-generated relations may only be proposed or inferred.")
        if egress_policy not in {EgressPolicy.LOCAL_ONLY, EgressPolicy.SHAREABLE}:
            raise McpWriteError("invalid_input", "Relation egress policy must be local_only or shareable.")
        brief_id = arguments.get("based_on_brief_id")
        section_index = arguments.get("based_on_brief_section_index")
        has_idea_endpoint = source_kind is NodeType.IDEA or target_kind is NodeType.IDEA
        if has_idea_endpoint:
            brief_id = self._text(brief_id, "based_on_brief_id")
            if type(section_index) is not int or not 0 <= section_index <= 7:
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
        assertion = RelationAssertion(
            owner_id=self.writes.owner_id,
            id=assertion_id,
            source_id=source_id,
            source_kind=source_kind,
            target_id=target_id,
            target_kind=target_kind,
            predicate=predicate,
            assertion_family_id=self._command_id("relation-family", idempotency_key),
            status=status,
            confidence=arguments.get("confidence"),
            expires_at=expires_at,
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
            expected_family_revision=None,
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
