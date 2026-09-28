"""MCP ingress for owner-approved research campaign lifecycle commands."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Mapping

from .founder_graph import DomainValidationError, EgressPolicy, Idea, Provenance, ResearchCampaign, ResearchRun, Status, validate_campaign_idea_reference
from .founder_graph_mcp_annotations import mcp_tool_annotations
from .founder_graph_research import revoke_research_campaign, validate_research_run_timing
from .founder_graph_write import GraphWriteError, GraphWritePort, IdempotencyConflictError, RevisionConflictError, WriteReceipt
from .idea_brief import IdeaBriefSection, IdeaBriefVersion, _REPORT_MARKDOWN_OMITTED
from .source_citations import evidence_lineage_is_current, researched_evidence_ids


class ResearchCampaignInputError(DomainValidationError):
    """Invalid caller intent for a research campaign MCP command."""


class ResearchCampaignUnavailableError(RuntimeError):
    """A required local research or brief persistence capability is unavailable."""


class _GraphWriteBriefStore:
    """Thin adapter over the existing in-memory write store; it owns no data."""

    def __init__(self, writes: Any) -> None:
        self.writes = writes
        self.owner_id = writes.owner_id

    def get(self, brief_id: str) -> IdeaBriefVersion | None:
        return self.writes.get_idea_brief(brief_id)

    def latest(self, root_id: str) -> IdeaBriefVersion | None:
        return self.writes.get_latest_idea_brief(root_id)

    def save(self, brief: IdeaBriefVersion, *, expected_latest_revision: int | None,
             idempotency_key: str, actor: str = "local-owner") -> WriteReceipt:
        return self.writes.save_idea_brief(
            brief,
            expected_latest_revision=expected_latest_revision,
            idempotency_key=idempotency_key,
            actor=actor,
        )


@dataclass(frozen=True, slots=True)
class ResearchWriteReceipt(WriteReceipt):
    """Standard write receipt plus a deliberately safe, bounded proposal view."""

    campaign_proposal: Mapping[str, Any] | None = None


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


def _proposal(campaign: ResearchCampaign, *, include_authorization: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {
        "purpose": campaign.purpose,
        "status": campaign.status.value,
        "authorized": campaign.authorized,
        "aggregate_revision": campaign.aggregate_revision,
        "scope": _json_value(campaign.scope),
        "questions": list(campaign.questions),
        "target_idea_id": campaign.target_idea_id,
        "allowed_categories": list(campaign.allowed_categories),
        "external_sources": list(campaign.external_sources),
        "trial_budget": campaign.trial_budget,
        "expires_at": campaign.expires_at.isoformat() if campaign.expires_at else None,
    }
    if include_authorization:
        result["authorization_snapshot_id"] = campaign.authorization_snapshot_id
        result["authorization_revision"] = campaign.authorization_revision
    return result


def _campaign_output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "purpose": {"type": "string"},
            "scope": {"type": "object", "additionalProperties": True},
            "questions": {"type": "array", "items": {"type": "string"}},
            "target_idea_id": {"type": ["string", "null"]},
            "allowed_categories": {"type": "array", "items": {"type": "string"}},
            "external_sources": {"type": "array", "items": {"type": "string"}},
            "trial_budget": {"type": "integer", "minimum": 1},
            "expires_at": {"type": ["string", "null"]},
            "authorization_snapshot_id": {"type": ["string", "null"]},
            "authorization_revision": {"type": "integer", "minimum": 0},
            "status": {"type": "string"},
            "authorized": {"type": "boolean"},
            "aggregate_revision": {"type": "integer", "minimum": 0},
        },
        "required": [
            "purpose", "status", "authorized", "aggregate_revision", "scope", "questions",
            "target_idea_id", "allowed_categories", "external_sources", "trial_budget", "expires_at",
        ],
        "additionalProperties": False,
    }


def _receipt_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "operation": {"type": "string", "minLength": 1},
            "target_id": {
                "type": "string", "minLength": 1,
                "description": "保存した記録のcanonical IDです。後続のDotsツール呼び出しでは、この値をそのまま使ってください。",
            },
            "target_type": {"type": "string", "minLength": 1},
            "revision": {"type": "integer", "minimum": 0},
            "idempotency_key": {"type": "string", "minLength": 1},
            "replayed": {"type": "boolean"},
            "source_revision_id": {"type": ["string", "null"]},
            "content_chunk_ids": {"type": "array", "items": {"type": "string", "minLength": 1}},
        },
        "required": [
            "operation", "target_id", "target_type", "revision", "idempotency_key", "replayed",
            "source_revision_id", "content_chunk_ids",
        ],
        "additionalProperties": False,
    }


class McpResearchCampaignSurface:
    """Create pending campaigns and require an explicit, revision-bound approval."""

    def __init__(self, writes: GraphWritePort, brief_store: Any | None = None) -> None:
        self.writes = writes
        if brief_store is None and all(callable(getattr(writes, name, None)) for name in (
            "save_idea_brief", "get_idea_brief", "get_latest_idea_brief",
        )):
            brief_store = _GraphWriteBriefStore(writes)
        self.brief_store = brief_store

    def tool_definitions(self) -> tuple[Mapping[str, Any], ...]:
        text = {"type": "string", "minLength": 1}
        ids = {"type": "array", "items": {"type": "string", "minLength": 1}}
        idempotency = {**text, "description": "同一操作の再試行時だけ同じ値を使ってください。別操作には新しい値が必要です。"}
        expected = {"type": "integer", "minimum": 0, "description": "現在表示されているCampaign revisionです。変更後は再取得してください。"}
        common_receipt = {
            "type": "object",
            "properties": {
                "operation": {"type": "string"}, "target_id": {"type": "string"},
                "target_type": {"type": "string"}, "revision": {"type": "integer"},
                "idempotency_key": {"type": "string"}, "replayed": {"type": "boolean"},
                "source_revision_id": {"type": ["string", "null"]},
                "content_chunk_ids": {"type": "array", "items": {"type": "string"}},
                "campaign_proposal": {"anyOf": [_campaign_output_schema(), {"type": "null"}]},
            },
            "required": ["operation", "target_id", "target_type", "revision", "idempotency_key", "replayed", "source_revision_id", "content_chunk_ids"],
            "additionalProperties": False,
        }
        definitions: tuple[Mapping[str, Any], ...] = (
            {
                "name": "create_research_campaign",
                "description": "外部調査を開始せず、目的・範囲・試行予算・期限を未許諾Campaignとして保存します。表示された提案を確認した本人が、別呼び出しで明示承認するまで許諾されません。owner、authorized、status、run_countはサーバーが決めます。",
                "readOnly": False,
                "annotations": mcp_tool_annotations(read_only=False, destructive=False),
                "inputSchema": {
                    "type": "object",
                    "required": ["purpose", "scope", "target_idea_id", "trial_budget", "expires_at", "idempotency_key", "expected_revision"],
                    "properties": {
                        "purpose": {**text, "maxLength": 1500},
                        "scope": {"type": "object", "description": "調査対象と範囲。個人情報や秘密は入れないでください。", "additionalProperties": True},
                        "questions": {"type": "array", "maxItems": 20, "items": {"type": "string", "minLength": 1, "maxLength": 500}},
                        "target_idea_id": {**text, "maxLength": 200},
                        "allowed_categories": {"type": "array", "maxItems": 30, "items": {"type": "string", "minLength": 1, "maxLength": 100}},
                        "external_sources": {"type": "array", "maxItems": 30, "items": {"type": "string", "minLength": 1, "maxLength": 200}},
                        "trial_budget": {"type": "integer", "minimum": 1, "maximum": 20},
                        "expires_at": {**text, "description": "ISO-8601 timezone付きの期限です。"},
                        "idempotency_key": idempotency,
                        "expected_revision": {"type": "integer", "const": 0},
                    },
                    "additionalProperties": False,
                },
                "outputSchema": common_receipt,
            },
            {
                "name": "approve_research_campaign",
                "description": "保存済みの目的・範囲・予算・期限を変更せずに許諾します。本人がその提案を確認し、confirmationに正確にapprovedを指定した場合だけ実行します。ResearchCampaignの許諾であり、外部調査をこの操作が開始・実行するものではありません。",
                "readOnly": False,
                "annotations": mcp_tool_annotations(read_only=False, destructive=True),
                "inputSchema": {
                    "type": "object", "required": ["campaign_id", "expected_revision", "confirmation", "idempotency_key"],
                    "properties": {
                        "campaign_id": {**text, "maxLength": 200}, "expected_revision": expected,
                        "confirmation": {"type": "string", "const": "approved", "description": "提案を本人が確認した後にのみ指定します。"},
                        "idempotency_key": idempotency,
                    }, "additionalProperties": False,
                }, "outputSchema": common_receipt,
            },
            {
                "name": "revoke_research_campaign",
                "description": "Campaignの許諾を取り消し、既存履歴を残したまま未許諾のREVOKED版を記録します。取消は外部調査処理を停止できるとは保証しません。",
                "readOnly": False,
                "annotations": mcp_tool_annotations(read_only=False, destructive=True),
                "inputSchema": {
                    "type": "object", "required": ["campaign_id", "expected_revision", "idempotency_key"],
                    "properties": {"campaign_id": {**text, "maxLength": 200}, "expected_revision": expected, "idempotency_key": idempotency},
                    "additionalProperties": False,
                }, "outputSchema": common_receipt,
            },
            {
                "name": "record_research_run",
                "description": "外部調査を開始せず、許諾済みCampaignに対するChatGPT側の終了済み調査結果だけをローカルに記録します。結果の状態はcompleted、partial、failed、cancelledから指定し、開始は許諾時刻以後、終了は現在かつ期限内のtimezone付き日時を明示してください。現行Campaign revisionと許諾snapshotも必要です。記録は試行予算を原子的に1回消費し、結果本文はこのreceiptに含めません。",
                "readOnly": False,
                "annotations": mcp_tool_annotations(read_only=False, destructive=True),
                "inputSchema": {
                    "type": "object",
                    "required": ["campaign_id", "expected_campaign_revision", "authorization_snapshot_id", "authorization_revision", "input_snapshot", "model_snapshot", "status", "results", "started_at", "finished_at", "idempotency_key"],
                    "properties": {
                        "campaign_id": {**text, "maxLength": 200},
                        "expected_campaign_revision": expected,
                        "authorization_snapshot_id": {**text, "maxLength": 200},
                        "authorization_revision": {"type": "integer", "minimum": 1},
                        "input_snapshot": {"type": "object", "description": "調査に渡した入力のprivateな再現用snapshot。ローカル保存し、返却しません。", "additionalProperties": True},
                        "model_snapshot": {**text, "maxLength": 300},
                        "status": {"type": "string", "enum": [Status.COMPLETED.value, Status.PARTIAL.value, Status.FAILED.value, Status.CANCELLED.value]},
                        "results": {"type": "object", "description": "ChatGPT側で得た終了結果。ローカル保存し、返却しません。", "additionalProperties": True},
                        "sources": {"type": "array", "maxItems": 30, "items": {"type": "string", "minLength": 1, "maxLength": 500}},
                        "evidence_ids": {"type": "array", "maxItems": 50, "items": {"type": "string", "minLength": 1, "maxLength": 200}},
                        "failures": {"type": "array", "maxItems": 30, "items": {"type": "string", "minLength": 1, "maxLength": 500}},
                        "started_at": {"type": "string", "description": "必須のISO-8601 timezone付き開始日時。許諾時刻以後である必要があります。"},
                        "finished_at": {"type": "string", "description": "必須のISO-8601 timezone付き終了日時。現在時刻以前かつCampaign期限内である必要があります。"},
                        "idempotency_key": idempotency,
                    },
                    "additionalProperties": False,
                },
                "outputSchema": _receipt_schema(),
            },
        )
        if self.brief_store is None:
            return definitions
        regular_brief = {
            "name": "save_idea_brief",
            "description": "既存のIdeaを8観点で育てます。旧版は残ります。未確認の内容を事実として記載せず、根拠IDがある場合だけ添えてください。未指定の観点は前版を維持します。初回はexpected_revision=0です。",
            "readOnly": False,
            "annotations": mcp_tool_annotations(read_only=False, destructive=True),
            "inputSchema": {
                "type": "object",
                "required": ["idea_id", "expected_revision", "sections", "idempotency_key"],
                "properties": {
                    "idea_id": {**text, "maxLength": 200},
                    "idea_lineage_root_id": {**text, "maxLength": 200},
                    "expected_revision": {"type": "integer", "minimum": 0},
                    "sections": {
                        "type": "array", "minItems": 1, "maxItems": 8,
                        "items": {
                            "type": "object", "required": ["index", "content"],
                            "properties": {
                                "index": {"type": "integer", "minimum": 0, "maximum": 7},
                                "content": {"type": "string", "maxLength": 4000},
                                "facts": ids, "inferences": ids, "unconfirmed": ids,
                                "owner_decisions": ids, "claim_ids": ids, "evidence_ids": ids,
                            }, "additionalProperties": False,
                        },
                    },
                    "change_reason": {"type": "string", "maxLength": 500},
                    "report_markdown": {"type": "string", "minLength": 1, "maxLength": 60000, "description": "図表・公開画像・出典リンクを含むレポート全文。8観点と同じ版に保存します。省略時は前版の本文を維持し、文字列を指定すると全文を置き換えます。HTMLは画面で実行しません。"},
                    "egress_policy": {"type": "string", "enum": [EgressPolicy.LOCAL_ONLY.value, EgressPolicy.SHAREABLE.value]},
                    "origin": {"type": "string", "enum": ["prior_research_import"], "description": "既に実施済みの過去調査を示す場合だけ指定します。現在のCampaign/Runの許諾や実行履歴は作りません。"},
                    "idempotency_key": idempotency,
                }, "additionalProperties": False,
            },
        }
        return definitions + (regular_brief, {
            "name": "save_researched_idea_brief",
            "description": "許諾済み調査を終えた後、Markdownレポート全文とIdeaの8観点・出典を同じ版に正式保存します。全文は必須です。対象IdeaとレポートがChatGPTへの共有に適する場合だけ、Ideaとこの保存操作でegress_policy=shareableを明示してください。省略時のlocal_only版はfetch_idea_briefで読み戻せません。保存成功後にfetch_idea_briefで最新版を読み戻し、その内容と実在Evidenceを根拠にlink_entities・classify_entityで意味関係を登録してください。概要全体で少なくとも1件の有効な公開出典Evidenceが必須です。指定したEvidenceは同じ所有者・現行・共有可の出典系譜であることを検証します。出典のない章へ架空IDを付けないでください。このツールは調査や事実の正しさを保証しません。出典不足や部分下書きはsave_idea_briefを使います。",
            "readOnly": False,
            "annotations": mcp_tool_annotations(read_only=False, destructive=True),
            "inputSchema": {
                "type": "object",
                "required": ["idea_id", "expected_revision", "sections", "research_run_ids", "report_markdown", "idempotency_key"],
                "properties": {
                    "idea_id": {**text, "maxLength": 200},
                    "idea_lineage_root_id": {**text, "maxLength": 200},
                    "expected_revision": {"type": "integer", "minimum": 0},
                    "sections": {
                        "type": "array", "minItems": 8, "maxItems": 8,
                        "items": {
                            "type": "object", "required": ["index", "content"],
                            "properties": {
                                "index": {"type": "integer", "minimum": 0, "maximum": 7},
                                "content": {"type": "string", "maxLength": 4000},
                                "facts": ids, "inferences": ids, "unconfirmed": ids,
                                "owner_decisions": ids, "claim_ids": ids, "evidence_ids": ids,
                            }, "additionalProperties": False,
                        },
                    },
                    "research_run_ids": {"type": "array", "minItems": 1, "maxItems": 20, "items": {**text, "maxLength": 200}},
                    "change_reason": {"type": "string", "maxLength": 500},
                    "report_markdown": {"type": "string", "minLength": 1, "maxLength": 60000, "description": "ChatGPTが作成した8章のMarkdownレポート全文。根拠を確認した出典URLを記し、必要に応じて表・公開画像・図を含めます。画像や数値を創作しません。8観点と出典IDの対応はsectionsにも保持します。"},
                    "egress_policy": {"type": "string", "enum": [EgressPolicy.LOCAL_ONLY.value, EgressPolicy.SHAREABLE.value]},
                    "idempotency_key": idempotency,
                }, "additionalProperties": False,
            },
            "outputSchema": _receipt_schema(),
        },)

    def call(self, tool_name: str, arguments: Mapping[str, Any], *, owner_id: str) -> ResearchWriteReceipt:
        if owner_id != self.writes.owner_id:
            raise ResearchCampaignInputError("request owner does not match the local owner")
        if not isinstance(arguments, Mapping):
            raise ResearchCampaignInputError("tool arguments must be an object")
        if tool_name == "create_research_campaign":
            return self._create(arguments)
        if tool_name == "approve_research_campaign":
            return self._approve(arguments)
        if tool_name == "revoke_research_campaign":
            return self._revoke(arguments)
        if tool_name == "record_research_run":
            return self._record_research_run(arguments)
        if tool_name == "save_idea_brief":
            return self._save_idea_brief(arguments)
        if tool_name == "save_researched_idea_brief":
            if self.brief_store is None:
                raise ResearchCampaignInputError("idea brief storage is unavailable on this connection")
            return self._save_researched_idea_brief(arguments)
        raise ResearchCampaignInputError("unknown research campaign tool")

    def _save_idea_brief(self, args: Mapping[str, Any]) -> WriteReceipt:
        if self.brief_store is None:
            raise ResearchCampaignInputError("idea brief storage is unavailable on this connection")
        if _brief_store_owner(self.brief_store) != self.writes.owner_id:
            raise ResearchCampaignInputError("idea brief store owner does not match the local owner")
        _reject_unknown(args, {"idea_id", "idea_lineage_root_id", "expected_revision", "sections", "report_markdown", "change_reason", "egress_policy", "origin", "idempotency_key"})
        key = _text(args.get("idempotency_key"), "idempotency_key")
        idea_id = _text(args.get("idea_id"), "idea_id", maximum=200)
        root_id = _text(args.get("idea_lineage_root_id", idea_id), "idea_lineage_root_id", maximum=200)
        expected = _revision(args.get("expected_revision"))
        raw_sections = args.get("sections")
        if not isinstance(raw_sections, (tuple, list)) or not 1 <= len(raw_sections) <= 8:
            raise ResearchCampaignInputError("sections must contain 1 through 8 viewpoints")
        try:
            sections = tuple(IdeaBriefSection(**item) for item in raw_sections)
        except (TypeError, ValueError) as error:
            raise ResearchCampaignInputError("section content is invalid") from error
        if not any(section.content.strip() for section in sections):
            raise ResearchCampaignInputError("at least one viewpoint needs content")
        report_markdown = args.get("report_markdown", _REPORT_MARKDOWN_OMITTED)
        if report_markdown is not _REPORT_MARKDOWN_OMITTED and (
            not isinstance(report_markdown, str) or not report_markdown.strip() or len(report_markdown) > 60_000
        ):
            raise ResearchCampaignInputError("report_markdown must contain 1 through 60000 characters")
        change_reason = args.get("change_reason", "initial")
        if not isinstance(change_reason, str) or not change_reason.strip() or len(change_reason) > 500:
            raise ResearchCampaignInputError("change_reason must contain 1 through 500 characters")
        egress_policy = args.get("egress_policy", EgressPolicy.LOCAL_ONLY.value)
        if egress_policy not in {EgressPolicy.LOCAL_ONLY.value, EgressPolicy.SHAREABLE.value}:
            raise ResearchCampaignInputError("egress_policy must be local_only or shareable")
        requested_origin = args.get("origin")
        if "origin" in args and requested_origin != "prior_research_import":
            raise ResearchCampaignInputError("origin must be prior_research_import when specified")
        brief_id = _command_id("idea-brief", key)
        previous = _latest_brief(self.brief_store, root_id)
        effective_origin = requested_origin if requested_origin is not None else (previous.origin if previous else None)
        prior_receipt = _lookup_receipt(self.writes, key, "save_idea_brief")
        existing = self.brief_store.get(brief_id)
        if prior_receipt is not None or existing is not None:
            if (
                (prior_receipt is not None and prior_receipt.target_id != brief_id)
                or existing is None
                or existing.revision != expected + 1
            ):
                raise IdempotencyConflictError("idempotency key was already used for a different brief")
            replay_report_markdown = (
                existing.report_markdown
                if report_markdown is _REPORT_MARKDOWN_OMITTED
                else report_markdown
            )
            if not _brief_matches(
                existing,
                root_id=root_id,
                idea_id=idea_id,
                sections=sections,
                run_ids=(),
                change_reason=change_reason,
                egress_policy=egress_policy,
                report_markdown=replay_report_markdown,
                origin=(requested_origin if requested_origin is not None else existing.origin),
            ):
                raise IdempotencyConflictError("idempotency key was already used for a different brief")
            receipt = prior_receipt or WriteReceipt("save_idea_brief", existing.id, "idea_brief_version", existing.revision, key)
            return replace(receipt, replayed=True)
        if previous is None:
            if expected != 0:
                raise RevisionConflictError("first brief expects revision 0")
            if effective_origin == "prior_research_import":
                raise ResearchCampaignInputError("prior-research imports must extend an existing Brief")
            brief = IdeaBriefVersion(
                owner_id=self.writes.owner_id, idea_lineage_root_id=root_id,
                based_on_idea_id=idea_id, sections=sections, id=brief_id,
                report_markdown=(
                    None if report_markdown is _REPORT_MARKDOWN_OMITTED else report_markdown
                ),
                change_reason=change_reason, egress_policy=egress_policy, origin=effective_origin,
            )
            expected_latest_revision = None
        else:
            if previous.revision != expected:
                raise RevisionConflictError("brief changed; reload its current revision")
            brief = replace(previous.revise(
                sections=sections, report_markdown=report_markdown, based_on_idea_id=idea_id, research_run_ids=(),
                change_reason=change_reason, egress_policy=egress_policy, origin=effective_origin,
            ), id=brief_id)
            expected_latest_revision = expected
        if brief.origin == "prior_research_import":
            if brief.research_run_ids or brief.egress_policy != EgressPolicy.SHAREABLE.value:
                raise ResearchCampaignInputError("prior-research Briefs require shareable citations and cannot claim Campaign Runs")
            idea = self.writes.get_node(idea_id)
            if not isinstance(idea, Idea) or idea.owner_id != self.writes.owner_id or idea.egress_policy is not EgressPolicy.SHAREABLE:
                raise ResearchCampaignInputError("prior-research Briefs require a shareable current Idea")
            evidence_ids = researched_evidence_ids(brief.sections)
            if not evidence_ids or any(
                not evidence_lineage_is_current(self.writes, evidence_id, self.writes.owner_id)
                for evidence_id in evidence_ids
            ):
                raise ResearchCampaignInputError("prior-research Briefs require current, shareable Evidence citations")
        try:
            return self.brief_store.save(
                brief, expected_latest_revision=expected_latest_revision, idempotency_key=key,
            )
        except (RevisionConflictError, IdempotencyConflictError):
            raise
        except Exception as error:
            raise ResearchCampaignUnavailableError("the idea brief could not be safely saved") from error

    def _create(self, args: Mapping[str, Any]) -> ResearchWriteReceipt:
        allowed = {"purpose", "scope", "questions", "target_idea_id", "allowed_categories", "external_sources", "trial_budget", "expires_at", "idempotency_key", "expected_revision"}
        _reject_unknown(args, allowed)
        key = _text(args.get("idempotency_key"), "idempotency_key")
        existing_receipt = _lookup_receipt(self.writes, key, "create_research_campaign")
        if args.get("expected_revision") != 0 or type(args.get("expected_revision")) is not int:
            raise ResearchCampaignInputError("new campaigns require expected_revision=0")
        purpose = _text(args.get("purpose"), "purpose", maximum=1500)
        scope = args.get("scope")
        if not isinstance(scope, Mapping):
            raise ResearchCampaignInputError("scope must be an object")
        scope_value = _json_value(scope)
        try:
            serialized_scope = json.dumps(scope_value, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as error:
            raise ResearchCampaignInputError("scope must contain only JSON values") from error
        if len(serialized_scope.encode("utf-8")) > 16_000:
            raise ResearchCampaignInputError("scope must not exceed 16000 UTF-8 bytes")
        budget = args.get("trial_budget")
        if type(budget) is not int or not 1 <= budget <= 20:
            raise ResearchCampaignInputError("trial_budget must be an integer from 1 through 20")
        expires_at = _parse_expiry(args.get("expires_at"))
        if existing_receipt is None and expires_at <= datetime.now(timezone.utc):
            raise ResearchCampaignInputError("expires_at must be in the future")
        idea_id = _text(args.get("target_idea_id"), "target_idea_id", maximum=200)
        questions = _strings(args.get("questions", ()), "questions", 20, 500)
        categories = _strings(args.get("allowed_categories", ()), "allowed_categories", 30, 100)
        sources = _strings(args.get("external_sources", ()), "external_sources", 30, 200)
        campaign_id = _command_id("campaign", key)
        campaign = ResearchCampaign(
            owner_id=self.writes.owner_id,
            id=campaign_id,
            purpose=purpose,
            scope=scope_value,
            questions=questions,
            target_idea_id=idea_id,
            allowed_categories=categories,
            external_sources=sources,
            trial_budget=budget,
            expires_at=expires_at,
            provenance=Provenance(actor="local-owner", operation="create_research_campaign", target_id=campaign_id, idempotency_key=key),
        )
        if existing_receipt is not None:
            saved = self._campaign(campaign_id)
            if existing_receipt.target_id != campaign_id or not _campaign_matches_request(
                saved, campaign,
            ):
                raise IdempotencyConflictError("idempotency key was already used for a different campaign")
            replay = replace(existing_receipt, replayed=True)
            return _receipt(replay, _proposal(saved))
        idea = self.writes.get_node(idea_id)
        if not isinstance(idea, Idea):
            raise ResearchCampaignInputError("target_idea_id must resolve to an Idea owned by the local owner")
        validate_campaign_idea_reference(campaign, idea)
        receipt = self.writes.put_node(campaign, idempotency_key=key, expected_revision=0, operation="create_research_campaign")
        saved = self.writes.get_node(campaign_id)
        if not isinstance(saved, ResearchCampaign):
            raise ResearchCampaignInputError("the campaign could not be safely read after saving")
        return _receipt(receipt, _proposal(saved))

    def _approve(self, args: Mapping[str, Any]) -> ResearchWriteReceipt:
        _reject_unknown(args, {"campaign_id", "expected_revision", "confirmation", "idempotency_key"})
        campaign_id = _text(args.get("campaign_id"), "campaign_id", maximum=200)
        key = _text(args.get("idempotency_key"), "idempotency_key")
        expected = _revision(args.get("expected_revision"))
        if args.get("confirmation") != "approved":
            raise ResearchCampaignInputError("confirmation must be exactly approved after reviewing the proposal")
        previous = self._campaign(campaign_id)
        replay = self._replay(key, "approve_research_campaign", campaign_id, expected)
        if replay is not None:
            current = self._campaign(campaign_id)
            return _receipt(replay, _proposal(current, include_authorization=True))
        _check_revision(previous, expected)
        at = datetime.now(timezone.utc)
        transitioned = previous.approve(
            approved_at=at,
            provenance=Provenance(actor="local-owner", operation="approve_research_campaign", target_id=campaign_id, occurred_at=at, idempotency_key=key),
        )
        receipt = self.writes.put_node(transitioned, idempotency_key=key, expected_revision=expected, operation="approve_research_campaign")
        return _receipt(receipt, _proposal(transitioned, include_authorization=True))

    def _revoke(self, args: Mapping[str, Any]) -> ResearchWriteReceipt:
        _reject_unknown(args, {"campaign_id", "expected_revision", "idempotency_key"})
        campaign_id = _text(args.get("campaign_id"), "campaign_id", maximum=200)
        key = _text(args.get("idempotency_key"), "idempotency_key")
        expected = _revision(args.get("expected_revision"))
        previous = self._campaign(campaign_id)
        replay = self._replay(key, "revoke_research_campaign", campaign_id, expected)
        if replay is not None:
            return _receipt(replay)
        _check_revision(previous, expected)
        if not previous.authorized:
            raise ResearchCampaignInputError("only an authorized campaign can be revoked")
        at = datetime.now(timezone.utc)
        provenance = Provenance(actor="local-owner", operation="revoke_research_campaign", target_id=campaign_id, occurred_at=at, idempotency_key=key)
        transitioned = revoke_research_campaign(previous, at=at, provenance=provenance)
        receipt = self.writes.put_node(transitioned, idempotency_key=key, expected_revision=expected, operation="revoke_research_campaign")
        return _receipt(receipt)

    def _record_research_run(self, args: Mapping[str, Any]) -> WriteReceipt:
        allowed = {
            "campaign_id", "expected_campaign_revision", "authorization_snapshot_id", "authorization_revision",
            "input_snapshot", "model_snapshot", "status", "results", "sources", "evidence_ids", "failures",
            "started_at", "finished_at", "idempotency_key",
        }
        _reject_unknown(args, allowed)
        key = _text(args.get("idempotency_key"), "idempotency_key")
        campaign_id = _text(args.get("campaign_id"), "campaign_id", maximum=200)
        expected = _revision(args.get("expected_campaign_revision"))
        snapshot_id = _text(args.get("authorization_snapshot_id"), "authorization_snapshot_id", maximum=200)
        authorization_revision = args.get("authorization_revision")
        if type(authorization_revision) is not int or authorization_revision < 1:
            raise ResearchCampaignInputError("authorization_revision must be a positive integer")
        try:
            run_status = Status(args.get("status"))
        except (TypeError, ValueError) as error:
            raise ResearchCampaignInputError("status must be completed, partial, failed, or cancelled") from error
        if run_status not in {Status.COMPLETED, Status.PARTIAL, Status.FAILED, Status.CANCELLED}:
            raise ResearchCampaignInputError("only terminal research run results can be recorded")
        input_snapshot = _bounded_mapping(args.get("input_snapshot"), "input_snapshot", 16_000)
        results = _bounded_mapping(args.get("results"), "results", 32_000)
        sources = _strings(args.get("sources", ()), "sources", 30, 500)
        evidence_ids = _strings(args.get("evidence_ids", ()), "evidence_ids", 50, 200)
        failures = _strings(args.get("failures", ()), "failures", 30, 500)
        model_snapshot = _text(args.get("model_snapshot"), "model_snapshot", maximum=300)
        started_at = _parse_timestamp(args.get("started_at"), "started_at")
        finished_at = _parse_timestamp(args.get("finished_at"), "finished_at")
        if started_at is None or finished_at is None:
            raise ResearchCampaignInputError("started_at and finished_at are required for a terminal Run")
        if finished_at < started_at:
            raise ResearchCampaignInputError("finished_at must not precede started_at")
        run_id = _command_id("run", key)
        run = ResearchRun(
            owner_id=self.writes.owner_id,
            id=run_id,
            campaign_id=campaign_id,
            authorization_snapshot_id=snapshot_id,
            authorization_revision=authorization_revision,
            input_snapshot=input_snapshot,
            model_snapshot=model_snapshot,
            sources=sources,
            evidence_ids=evidence_ids,
            results=results,
            failures=failures,
            status=run_status,
            egress_policy=EgressPolicy.LOCAL_ONLY,
            started_at=started_at,
            finished_at=finished_at,
            provenance=Provenance(actor="local-owner", operation="record_research_run", target_id=run_id, source_id=campaign_id, idempotency_key=key),
        )
        prior_receipt = _lookup_receipt(self.writes, key, "record_research_run")
        if prior_receipt is None:
            campaign = self._campaign(campaign_id)
            validate_research_run_timing(run, campaign)
        return self.writes.record_research_run(
            run,
            expected_campaign_revision=expected,
            idempotency_key=key,
        )

    def _save_researched_idea_brief(self, args: Mapping[str, Any]) -> WriteReceipt:
        if self.brief_store is None:
            raise ResearchCampaignInputError("idea brief storage is unavailable on this connection")
        if _brief_store_owner(self.brief_store) != self.writes.owner_id:
            raise ResearchCampaignInputError("idea brief store owner does not match the local owner")
        allowed = {
            "idea_id", "idea_lineage_root_id", "expected_revision", "sections", "research_run_ids",
            "change_reason", "egress_policy", "report_markdown", "idempotency_key",
        }
        _reject_unknown(args, allowed)
        key = _text(args.get("idempotency_key"), "idempotency_key")
        idea_id = _text(args.get("idea_id"), "idea_id", maximum=200)
        root_id = _text(args.get("idea_lineage_root_id", idea_id), "idea_lineage_root_id", maximum=200)
        expected = _revision(args.get("expected_revision"))
        run_ids = _strings(args.get("research_run_ids"), "research_run_ids", 20, 200)
        if not run_ids:
            raise ResearchCampaignInputError("research_run_ids must contain at least one completed Run")
        raw_sections = args.get("sections")
        if not isinstance(raw_sections, (tuple, list)) or len(raw_sections) != 8:
            raise ResearchCampaignInputError("researched IdeaBrief requires exactly eight viewpoints")
        try:
            sections = tuple(IdeaBriefSection(**item) for item in raw_sections)
        except (TypeError, ValueError) as error:
            raise ResearchCampaignInputError("section content is invalid") from error
        report_markdown = args.get("report_markdown")
        if not isinstance(report_markdown, str) or not report_markdown.strip() or len(report_markdown) > 60_000:
            raise ResearchCampaignInputError("report_markdown must contain 1 through 60000 characters")
        if {section.index for section in sections} != set(range(8)):
            raise ResearchCampaignInputError("researched IdeaBrief must provide each viewpoint exactly once")
        change_reason = args.get("change_reason", "researched brief")
        if not isinstance(change_reason, str) or not change_reason.strip() or len(change_reason) > 500:
            raise ResearchCampaignInputError("change_reason must contain 1 through 500 characters")
        egress_policy = args.get("egress_policy", EgressPolicy.LOCAL_ONLY.value)
        if egress_policy not in {EgressPolicy.LOCAL_ONLY.value, EgressPolicy.SHAREABLE.value}:
            raise ResearchCampaignInputError("egress_policy must be local_only or shareable")

        brief_id = _command_id("idea-brief", key)
        prior_receipt = _lookup_receipt(self.writes, key, "save_idea_brief")
        existing = self.brief_store.get(brief_id)
        if prior_receipt is not None or existing is not None:
            if (prior_receipt is not None and prior_receipt.target_id != brief_id) or existing is None or existing.revision != expected + 1 or not _brief_matches(
                existing, root_id=root_id, idea_id=idea_id, sections=sections,
                run_ids=run_ids, change_reason=change_reason, egress_policy=egress_policy,
                report_markdown=report_markdown,
            ):
                raise IdempotencyConflictError("idempotency key was already used for a different brief")
            receipt = prior_receipt or WriteReceipt("save_idea_brief", existing.id, "idea_brief_version", existing.revision, key)
            return replace(receipt, operation="save_researched_idea_brief", replayed=True)
        evidence_ids = researched_evidence_ids(sections)
        if not evidence_ids:
            raise ResearchCampaignInputError("researched IdeaBrief requires at least one current, shareable Evidence citation")
        if any(not evidence_lineage_is_current(self.writes, evidence_id, self.writes.owner_id) for evidence_id in evidence_ids):
            raise ResearchCampaignInputError("researched IdeaBrief contains an invalid or non-current Evidence citation")
        previous = _latest_brief(self.brief_store, root_id)
        if previous is None:
            if expected != 0:
                raise RevisionConflictError("first brief expects revision 0")
            brief = IdeaBriefVersion(
                owner_id=self.writes.owner_id, idea_lineage_root_id=root_id, based_on_idea_id=idea_id,
                sections=sections, id=brief_id, research_run_ids=run_ids,
                report_markdown=report_markdown,
                change_reason=change_reason, egress_policy=egress_policy,
            )
            expected_latest_revision = None
        else:
            if previous.revision != expected:
                raise RevisionConflictError("brief changed; reload its current revision")
            brief = replace(previous.revise(
                sections=sections, report_markdown=report_markdown, based_on_idea_id=idea_id, research_run_ids=run_ids,
                change_reason=change_reason, egress_policy=egress_policy,
            ), id=brief_id)
            expected_latest_revision = expected
        try:
            receipt = self.brief_store.save(
                brief, expected_latest_revision=expected_latest_revision, idempotency_key=key,
            )
        except (RevisionConflictError, IdempotencyConflictError):
            raise
        except Exception as error:
            raise ResearchCampaignUnavailableError("the researched idea brief could not be safely saved") from error
        return replace(receipt, operation="save_researched_idea_brief")

    def _campaign(self, campaign_id: str) -> ResearchCampaign:
        node = self.writes.get_node(campaign_id)
        if not isinstance(node, ResearchCampaign) or node.owner_id != self.writes.owner_id:
            raise ResearchCampaignInputError("the requested campaign was not found")
        return node

    def _replay(self, key: str, operation: str, campaign_id: str, expected: int) -> WriteReceipt | None:
        lookup = getattr(self.writes, "get_write_receipt", None)
        if not callable(lookup):
            return None
        receipt = lookup(key, operation=operation)
        if receipt is None:
            return None
        if receipt.target_id != campaign_id or receipt.revision != expected + 1:
            raise IdempotencyConflictError("idempotency key was already used for a different command")
        return WriteReceipt(
            receipt.operation, receipt.target_id, receipt.target_type, receipt.revision,
            receipt.idempotency_key, replayed=True, source_revision_id=receipt.source_revision_id,
            content_chunk_ids=receipt.content_chunk_ids,
        )


def _receipt(receipt: WriteReceipt, proposal: Mapping[str, Any] | None = None) -> ResearchWriteReceipt:
    return ResearchWriteReceipt(
        receipt.operation, receipt.target_id, receipt.target_type, receipt.revision,
        receipt.idempotency_key, receipt.replayed, receipt.source_revision_id,
        receipt.content_chunk_ids, proposal,
    )


def _lookup_receipt(writes: Any, key: str, operation: str) -> WriteReceipt | None:
    lookup = getattr(writes, "get_write_receipt", None)
    return lookup(key, operation=operation) if callable(lookup) else None


def _brief_store_owner(store: Any) -> str | None:
    owner_id = getattr(store, "owner_id", None)
    if isinstance(owner_id, str):
        return owner_id
    gateway = getattr(store, "gateway", None)
    return getattr(gateway, "owner_id", None)


def _latest_brief(store: Any, root_id: str) -> IdeaBriefVersion | None:
    latest = getattr(store, "latest", None) or getattr(store, "get_latest", None)
    if not callable(latest):
        raise ResearchCampaignUnavailableError("the local idea brief store is unavailable")
    return latest(root_id)


def _brief_matches(
    brief: IdeaBriefVersion, *, root_id: str, idea_id: str,
    sections: tuple[IdeaBriefSection, ...], run_ids: tuple[str, ...],
    change_reason: str, egress_policy: str, report_markdown: str | None = None, origin: str | None = None,
) -> bool:
    return (
        brief.idea_lineage_root_id == root_id
        and brief.based_on_idea_id == idea_id
        and all(brief.sections[section.index] == section for section in sections)
        and tuple(brief.research_run_ids) == run_ids
        and brief.change_reason == change_reason
        and brief.egress_policy == egress_policy
        and brief.report_markdown == report_markdown
        and brief.origin == origin
    )


def _campaign_matches_request(saved: ResearchCampaign, requested: ResearchCampaign) -> bool:
    return all(getattr(saved, field) == getattr(requested, field) for field in (
        "purpose", "scope", "questions", "target_idea_id", "allowed_categories",
        "external_sources", "trial_budget", "expires_at",
    ))


def _command_id(prefix: str, key: str) -> str:
    from hashlib import sha256

    return f"{prefix}_{sha256(key.encode('utf-8')).hexdigest()[:32]}"


def _text(value: Any, field_name: str, *, maximum: int = 2000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ResearchCampaignInputError(f"{field_name} must be a non-empty string of at most {maximum} characters")
    return value.strip()


def _strings(value: Any, field_name: str, max_items: int, max_length: int) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)) or len(value) > max_items:
        raise ResearchCampaignInputError(f"{field_name} must be an array of at most {max_items} strings")
    result = tuple(_text(item, field_name, maximum=max_length) for item in value)
    if len(set(result)) != len(result):
        raise ResearchCampaignInputError(f"{field_name} must not contain duplicates")
    return result


def _parse_expiry(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ResearchCampaignInputError("expires_at must be an ISO-8601 timestamp with timezone")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ResearchCampaignInputError("expires_at must be an ISO-8601 timestamp with timezone") from error
    if result.tzinfo is None or result.utcoffset() is None:
        raise ResearchCampaignInputError("expires_at must include a timezone")
    return result.astimezone(timezone.utc)


def _parse_timestamp(value: Any, field_name: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ResearchCampaignInputError(f"{field_name} must be an ISO-8601 timestamp with timezone")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ResearchCampaignInputError(f"{field_name} must be an ISO-8601 timestamp with timezone") from error
    if result.tzinfo is None or result.utcoffset() is None:
        raise ResearchCampaignInputError(f"{field_name} must include a timezone")
    return result.astimezone(timezone.utc)


def _bounded_mapping(value: Any, field_name: str, maximum_bytes: int) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ResearchCampaignInputError(f"{field_name} must be an object")
    safe_value = _json_value(value)
    try:
        serialized = json.dumps(safe_value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as error:
        raise ResearchCampaignInputError(f"{field_name} must contain bounded JSON values") from error
    if len(serialized.encode("utf-8")) > maximum_bytes:
        raise ResearchCampaignInputError(f"{field_name} exceeds its {maximum_bytes}-byte limit")
    return safe_value


def _revision(value: Any) -> int:
    if type(value) is not int or value < 0:
        raise ResearchCampaignInputError("expected_revision must be a non-negative integer")
    return value


def _check_revision(campaign: ResearchCampaign, expected: int) -> None:
    if campaign.aggregate_revision != expected:
        raise RevisionConflictError("expected campaign revision does not match current revision")


def _reject_unknown(args: Mapping[str, Any], allowed: set[str]) -> None:
    if set(args).difference(allowed):
        raise ResearchCampaignInputError("unknown campaign tool arguments are not accepted")
