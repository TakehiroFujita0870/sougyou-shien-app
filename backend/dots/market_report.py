"""Deterministic local contract for evidence-backed market reports."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


EvidenceClassification = Literal["supporting", "counter", "unverified"]
DecisionStatus = Literal["active", "expired"]
CardUpdateStatus = Literal["proposed", "approved"]
CompetitorCategory = Literal["direct", "indirect", "alternative"]
JudgmentKind = Literal["winning_move", "opportunity"]


class ReportEvidence(BaseModel):
    id: str = Field(min_length=1, max_length=200)
    locator: str = Field(min_length=1, max_length=2000)
    excerpt: str = Field(min_length=1, max_length=4000)
    classification: EvidenceClassification


class PastDecision(BaseModel):
    decision: str = Field(min_length=1, max_length=2000)
    rationale: str = Field(min_length=1, max_length=4000)
    status: DecisionStatus


class CompetitorEntry(BaseModel):
    id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    category: CompetitorCategory
    comparison_axis: str = Field(min_length=1, max_length=500)
    evidence_ids: list[str] = Field(default_factory=list, max_length=100)


class PotentialEntrantRisk(BaseModel):
    description: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=100)


class OwnerJudgment(BaseModel):
    kind: JudgmentKind
    statement: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=100)


class MarketReportRequest(BaseModel):
    idea_id: str = Field(min_length=1, max_length=200)
    idea_title: str = Field(min_length=1, max_length=200)
    evidence: list[ReportEvidence] = Field(default_factory=list, max_length=100)
    past_decisions: list[PastDecision] = Field(default_factory=list, max_length=100)
    competitors: list[CompetitorEntry] = Field(default_factory=list, max_length=100)
    potential_entrant_risks: list[PotentialEntrantRisk] = Field(default_factory=list, max_length=100)
    owner_judgments: list[OwnerJudgment] = Field(default_factory=list, max_length=100)


class ReportSection(BaseModel):
    heading: str
    conclusion: str


class CardUpdate(BaseModel):
    status: CardUpdateStatus
    proposal: str
    approved_at: datetime | None = None


class MarketReportResponse(BaseModel):
    id: str
    idea_id: str
    market_outlook: ReportSection
    competitive_difference: ReportSection
    opportunity_focus: ReportSection
    supporting_evidence: list[ReportEvidence]
    counter_evidence: list[ReportEvidence]
    unverified_items: list[str]
    card_update: CardUpdate
    competitors: list[CompetitorEntry]
    potential_entrant_risks: list[PotentialEntrantRisk]
    owner_judgments: list[OwnerJudgment]
    evidence: list[ReportEvidence]
    ai_inference: list[str]


@dataclass
class StoredMarketReport:
    owner_id: str
    response: MarketReportResponse


class InMemoryMarketReportRepository:
    """Owner-scoped, credential-free storage for local contract validation."""

    def __init__(self) -> None:
        self._reports: dict[str, StoredMarketReport] = {}

    def create(self, owner_id: str, request: MarketReportRequest) -> MarketReportResponse:
        evidence_by_id = {item.id: item for item in request.evidence}
        references = [evidence_id for item in (*request.competitors, *request.potential_entrant_risks, *request.owner_judgments) for evidence_id in item.evidence_ids]
        if any(evidence_id not in evidence_by_id for evidence_id in references):
            raise ValueError("evidence reference not found")
        supporting = [item for item in request.evidence if item.classification == "supporting"]
        counter = [item for item in request.evidence if item.classification == "counter"]
        unverified = [item.excerpt for item in request.evidence if item.classification == "unverified"]
        response = MarketReportResponse(
            id=str(uuid4()),
            idea_id=request.idea_id,
            market_outlook=ReportSection(
                heading="市場の見込み",
                conclusion=_market_conclusion(len(supporting), len(counter), len(unverified)),
            ),
            competitive_difference=ReportSection(
                heading="競合との違い",
                conclusion=_difference_conclusion(request.past_decisions),
            ),
            opportunity_focus=ReportSection(
                heading="攻めどころの特定",
                conclusion=_opportunity_conclusion(request.idea_title, supporting, unverified),
            ),
            supporting_evidence=supporting,
            counter_evidence=counter,
            unverified_items=unverified,
            card_update=CardUpdate(status="proposed", proposal=_proposal(request.idea_title, supporting, counter)),
            competitors=request.competitors,
            potential_entrant_risks=request.potential_entrant_risks,
            owner_judgments=request.owner_judgments,
            evidence=request.evidence,
            ai_inference=[
                _market_conclusion(len(supporting), len(counter), len(unverified)),
                _difference_conclusion(request.past_decisions),
                _opportunity_conclusion(request.idea_title, supporting, unverified),
            ],
        )
        self._reports[response.id] = StoredMarketReport(owner_id=owner_id, response=response)
        return response

    def get(self, owner_id: str, report_id: str) -> MarketReportResponse | None:
        stored = self._reports.get(report_id)
        return stored.response if stored and stored.owner_id == owner_id else None

    def approve(self, owner_id: str, report_id: str) -> MarketReportResponse | None:
        report = self.get(owner_id, report_id)
        if report is None:
            return None
        if report.card_update.status == "proposed":
            report.card_update = CardUpdate(
                status="approved",
                proposal=report.card_update.proposal,
                approved_at=datetime.now(UTC),
            )
        return report


def _market_conclusion(supporting: int, counter: int, unverified: int) -> str:
    if supporting > counter:
        return f"根拠{supporting}件が反対材料{counter}件を上回るため、検証を続ける価値があります。未確認は{unverified}件です。"
    if counter:
        return f"反対材料{counter}件を解消するまでは市場性を確定できません。根拠は{supporting}件、未確認は{unverified}件です。"
    return f"市場性を判断する根拠が不足しています。未確認は{unverified}件です。"


def _difference_conclusion(decisions: list[PastDecision]) -> str:
    active = [item.decision for item in decisions if item.status == "active"]
    if active:
        return f"過去判断「{active[0]}」を、既存の選択肢との違いとして検証します。"
    return "競合との違いを裏付ける過去判断はまだありません。"


def _opportunity_conclusion(title: str, supporting: list[ReportEvidence], unverified: list[str]) -> str:
    if supporting:
        return f"「{title}」は根拠「{supporting[0].excerpt}」に対応する利用場面から検証します。"
    if unverified:
        return f"「{title}」は未確認事項「{unverified[0]}」の確認を先に進めます。"
    return f"「{title}」は追加の調査根拠を集めてから対象場面を絞ります。"


def _proposal(title: str, supporting: list[ReportEvidence], counter: list[ReportEvidence]) -> str:
    if supporting:
        return f"仮説カードに「{title}」の根拠として「{supporting[0].excerpt}」を追記する提案です。"
    if counter:
        return f"仮説カードに反対材料「{counter[0].excerpt}」を追記する提案です。"
    return f"仮説カードに「{title}」の未確認事項を追記する提案です。"
