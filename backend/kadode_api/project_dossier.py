"""Deterministic local assembler for a project's five business questions."""

from typing import Literal

from pydantic import BaseModel, Field

from .execution_plan import ExecutionPlanInput, evaluate_execution_plan
from .market_report import MarketReportResponse, OwnerJudgment, ReportEvidence
from .unit_economics import ScenarioInput, UnitEconomicsPlan, calculate_plan


SectionStatus = Literal["confirmed", "unconfirmed"]
FreshnessStatus = Literal["local_input", "unconfirmed", "missing"]


class SourceReference(BaseModel):
    source_id: str
    locator: str
    summary: str


class OwnerDecision(BaseModel):
    statement: str
    source_ids: list[str] = Field(default_factory=list)


class BusinessDefinition(BaseModel):
    facts: list[SourceReference] = Field(default_factory=list)
    ai_inference: list[str] = Field(default_factory=list)
    owner_decisions: list[OwnerDecision] = Field(default_factory=list)


class DossierRequest(BaseModel):
    project_id: str = Field(min_length=1, max_length=200)
    business_definition: BusinessDefinition = Field(default_factory=BusinessDefinition)
    market_report_id: str | None = Field(default=None, min_length=1, max_length=200)
    unit_economics_scenarios: tuple[ScenarioInput, ...] | None = None
    execution_plan: ExecutionPlanInput | None = None


class DossierSection(BaseModel):
    question: str
    status: SectionStatus
    facts: list[SourceReference] = Field(default_factory=list)
    ai_inference: list[str] = Field(default_factory=list)
    owner_decisions: list[OwnerDecision] = Field(default_factory=list)
    missing_reasons: list[str] = Field(default_factory=list)


class SourceFreshness(BaseModel):
    status: FreshnessStatus
    source_ids: list[str] = Field(default_factory=list)
    reason: str | None = None


class ProjectDossier(BaseModel):
    project_id: str
    sections: list[DossierSection]
    contradictory_evidence: list[SourceReference]
    source_freshness: dict[str, SourceFreshness]
    disclaimer: str


def assemble_dossier(request: DossierRequest, report: MarketReportResponse | None) -> ProjectDossier:
    finance = calculate_plan(request.unit_economics_scenarios) if request.unit_economics_scenarios else None
    execution = evaluate_execution_plan(request.execution_plan) if request.execution_plan else None
    sections = [
        _business_section(request.business_definition),
        _market_section(report),
        _competitor_section(report),
        _profit_section(finance),
        _feasibility_section(execution),
    ]
    contradictions = [_reference(item) for item in report.counter_evidence] if report else []
    return ProjectDossier(
        project_id=request.project_id,
        sections=sections,
        contradictory_evidence=contradictions,
        source_freshness=_freshness(request, report, finance, execution),
        disclaimer="This deterministic local dossier is not financial, lending, tax, legal, or market advice.",
    )


def _business_section(definition: BusinessDefinition) -> DossierSection:
    missing = [] if _has_business_content(definition) else ["business_definition_missing"]
    return DossierSection(
        question="どんな事業",
        status="confirmed" if not missing else "unconfirmed",
        facts=definition.facts,
        ai_inference=definition.ai_inference,
        owner_decisions=definition.owner_decisions,
        missing_reasons=missing,
    )


def _market_section(report: MarketReportResponse | None) -> DossierSection:
    if report is None:
        return _missing_section("市場はある", "market_report_missing")
    return DossierSection(
        question="市場はある",
        status="confirmed" if report.evidence else "unconfirmed",
        facts=[_reference(item) for item in report.evidence],
        ai_inference=[report.market_outlook.conclusion, report.opportunity_focus.conclusion],
        missing_reasons=[] if report.evidence else ["market_evidence_missing"],
    )


def _competitor_section(report: MarketReportResponse | None) -> DossierSection:
    if report is None:
        return _missing_section("競合は誰", "market_report_missing")
    evidence = {item.id: item for item in report.evidence}
    references = [
        _reference(evidence[evidence_id])
        for competitor in (*report.competitors, *report.potential_entrant_risks)
        for evidence_id in competitor.evidence_ids
    ]
    decisions = [_decision(item) for item in report.owner_judgments]
    missing = [] if report.competitors else ["competitors_missing"]
    return DossierSection(
        question="競合は誰",
        status="confirmed" if not missing else "unconfirmed",
        facts=references,
        ai_inference=[report.competitive_difference.conclusion],
        owner_decisions=decisions,
        missing_reasons=missing,
    )


def _profit_section(plan: UnitEconomicsPlan | None) -> DossierSection:
    if plan is None:
        return _missing_section("利益はでる", "unit_economics_missing")
    facts = [
        SourceReference(source_id=f"unit-economics:{item.name}", locator="local:unit-economics", summary=f"{item.name}: operating_profit={item.operating_profit.amount} {item.operating_profit.currency}")
        for item in plan.scenarios
    ]
    return DossierSection(question="利益はでる", status="confirmed", facts=facts, ai_inference=[], owner_decisions=[])


def _feasibility_section(plan: object | None) -> DossierSection:
    if plan is None:
        return _missing_section("実現できる", "execution_plan_missing")
    return DossierSection(
        question="実現できる",
        status="confirmed",
        facts=[SourceReference(source_id="execution-plan", locator="local:execution-plan", summary="reversible small experiment is within validated time and household-fund limits")],
        ai_inference=[],
        owner_decisions=[],
    )


def _missing_section(question: str, reason: str) -> DossierSection:
    return DossierSection(question=question, status="unconfirmed", missing_reasons=[reason])


def _reference(evidence: ReportEvidence) -> SourceReference:
    return SourceReference(source_id=evidence.id, locator=evidence.locator, summary=evidence.excerpt)


def _decision(judgment: OwnerJudgment) -> OwnerDecision:
    return OwnerDecision(statement=judgment.statement, source_ids=judgment.evidence_ids)


def _has_business_content(definition: BusinessDefinition) -> bool:
    return bool(definition.facts or definition.ai_inference or definition.owner_decisions)


def _freshness(
    request: DossierRequest, report: MarketReportResponse | None, finance: UnitEconomicsPlan | None, execution: object | None
) -> dict[str, SourceFreshness]:
    return {
        "business_definition": SourceFreshness(
            status="local_input" if _has_business_content(request.business_definition) else "missing",
            source_ids=[item.source_id for item in request.business_definition.facts],
            reason=None if _has_business_content(request.business_definition) else "business_definition_missing",
        ),
        "market_report": SourceFreshness(
            status="unconfirmed" if report else "missing",
            source_ids=[item.id for item in report.evidence] if report else [],
            reason="source_update_time_unavailable" if report else "market_report_missing",
        ),
        "unit_economics": SourceFreshness(
            status="local_input" if finance else "missing",
            source_ids=[f"unit-economics:{item.name}" for item in finance.scenarios] if finance else [],
            reason=None if finance else "unit_economics_missing",
        ),
        "execution_plan": SourceFreshness(
            status="local_input" if execution else "missing",
            source_ids=["execution-plan"] if execution else [],
            reason=None if execution else "execution_plan_missing",
        ),
    }
