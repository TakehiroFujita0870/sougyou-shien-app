"""PII-free, internally coherent Japanese demo dataset for admin demonstrations."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class DemoProvenance(BaseModel):
    dataset_id: str = "kadode-admin-demo-v1"
    status: Literal["synthetic_demo"] = "synthetic_demo"
    notice: str = "これは管理者デモ専用の合成データであり、実在の人物・企業・取引を表しません。"
    generated_on: str = "2026-08-09"


class DemoMessage(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    text: str
    candidate_id: str | None = None


class DemoCompetitor(BaseModel):
    id: str
    name: str
    category: Literal["direct", "indirect", "alternative"]
    evidence_id: str


class DemoSection(BaseModel):
    key: Literal["what", "market", "competitors", "profit", "feasibility"]
    title: str
    facts: list[str]
    inference: list[str]
    owner_decision: str
    source_ids: list[str]


class DemoFinancials(BaseModel):
    currency: Literal["JPY"] = "JPY"
    period: Literal["monthly"] = "monthly"
    price_per_sale: int = 48000
    variable_cost_per_sale: int = 12000
    fixed_cost: int = 90000
    capacity_per_month: int = 8
    break_even_sales: int = 3
    scenarios: dict[Literal["base", "upside", "downside"], int]


class DemoExecution(BaseModel):
    weekly_hours_limit: int = 6
    household_fund_limit: int = 50000
    experiment_budget: int = 30000
    withdrawal_condition: str
    resources: list[str]
    roadmap: list[str]


class DemoKnowledgeAsset(BaseModel):
    id: str
    project_id: str
    kind: Literal["background", "source", "decision", "document_metadata"]
    title: str
    source_id: str | None = None
    locator: str | None = None
    revision: str = "r1"


class DemoDecision(BaseModel):
    id: str
    project_id: str
    decision: str
    rationale: str
    evidence_ids: list[str]


class AdminDemoDataset(BaseModel):
    provenance: DemoProvenance = Field(default_factory=DemoProvenance)
    owner_id: str = "demo-owner"
    conversation_id: str = "demo-conversation-001"
    messages: list[DemoMessage]
    adopted_project_id: str = "demo-project-001"
    project_title: str
    sections: list[DemoSection]
    competitors: list[DemoCompetitor]
    financials: DemoFinancials
    execution: DemoExecution
    knowledge_assets: list[DemoKnowledgeAsset]
    decisions: list[DemoDecision]

    @model_validator(mode="after")
    def validate_references(self) -> "AdminDemoDataset":
        section_keys = [item.key for item in self.sections]
        if section_keys != ["what", "market", "competitors", "profit", "feasibility"]:
            raise ValueError("five_sections_must_be_in_plain_language_order")
        evidence_ids = {asset.id for asset in self.knowledge_assets if asset.kind == "source"}
        if any(item.evidence_id not in evidence_ids for item in self.competitors):
            raise ValueError("competitor_evidence_reference_invalid")
        if any(source_id not in evidence_ids for section in self.sections for source_id in section.source_ids):
            raise ValueError("section_source_reference_invalid")
        if any(source_id not in evidence_ids for decision in self.decisions for source_id in decision.evidence_ids):
            raise ValueError("decision_evidence_reference_invalid")
        if self.financials.price_per_sale - self.financials.variable_cost_per_sale <= 0:
            raise ValueError("contribution_margin_must_be_positive")
        expected_break_even = (self.financials.fixed_cost + (self.financials.price_per_sale - self.financials.variable_cost_per_sale) - 1) // (self.financials.price_per_sale - self.financials.variable_cost_per_sale)
        if self.financials.break_even_sales != expected_break_even:
            raise ValueError("break_even_reference_invalid")
        if any(asset.project_id != self.adopted_project_id for asset in self.knowledge_assets):
            raise ValueError("knowledge_project_reference_invalid")
        if any(decision.project_id != self.adopted_project_id for decision in self.decisions):
            raise ValueError("decision_project_reference_invalid")
        return self


def build_admin_demo_dataset() -> AdminDemoDataset:
    sources = [
        DemoKnowledgeAsset(id="demo-source-market", project_id="demo-project-001", kind="source", title="合成市場メモ", locator="fixture:market/1"),
        DemoKnowledgeAsset(id="demo-source-customer", project_id="demo-project-001", kind="source", title="匿名化済み課題要約", locator="fixture:customer/1"),
        DemoKnowledgeAsset(id="demo-knowledge-background", project_id="demo-project-001", kind="background", title="地域製造業の現場改善背景"),
        DemoKnowledgeAsset(id="demo-knowledge-decision", project_id="demo-project-001", kind="decision", title="週末検証を先に行う判断"),
        DemoKnowledgeAsset(id="demo-document-001", project_id="demo-project-001", kind="document_metadata", title="合成事業メモ", source_id="demo-source-market", locator="fixture:document/1"),
    ]
    return AdminDemoDataset(
        messages=[
            DemoMessage(id="msg-1", role="user", text="現場改善の経験を小さなサービスにしたい", candidate_id="candidate-1"),
            DemoMessage(id="msg-2", role="assistant", text="週末の小規模検証から始める案を作りました。", candidate_id="candidate-1"),
            DemoMessage(id="msg-3", role="user", text="プロジェクトに採用して深掘り", candidate_id="candidate-1"),
        ],
        project_title="現場改善ミニ診断（合成デモ）",
        sections=[
            DemoSection(key="what", title="どんな事業", facts=["製造現場の改善候補を短時間で整理する"], inference=["経験知を診断テンプレートへ転換できる可能性"], owner_decision="週末検証を採用", source_ids=["demo-source-customer"]),
            DemoSection(key="market", title="市場はある", facts=["合成市場メモに対象業務の反復課題を記録"], inference=["初期顧客候補は小規模事業者"], owner_decision="3件のヒアリング相当テストを行う", source_ids=["demo-source-market"]),
            DemoSection(key="competitors", title="競合は誰", facts=["3分類を比較軸付きで保持"], inference=["短納期と現場言語が差別化仮説"], owner_decision="価格より導入負担を優先", source_ids=["demo-source-market"]),
            DemoSection(key="profit", title="利益はでる", facts=["月次base/upside/downsideを決定的計算"], inference=["baseでは小容量でも固定費回収を試せる"], owner_decision="上限内の実験だけ実施", source_ids=["demo-source-market"]),
            DemoSection(key="feasibility", title="実現できる", facts=["週6時間・家計資金5万円以内"], inference=["可逆な週末実験が現実的"], owner_decision="条件超過で撤退", source_ids=["demo-source-customer"]),
        ],
        competitors=[
            DemoCompetitor(id="comp-direct", name="同種の現場診断サービス（合成）", category="direct", evidence_id="demo-source-market"),
            DemoCompetitor(id="comp-indirect", name="専門家への個別相談（合成）", category="indirect", evidence_id="demo-source-market"),
            DemoCompetitor(id="comp-alternative", name="社内改善会議（合成）", category="alternative", evidence_id="demo-source-market"),
        ],
        financials=DemoFinancials(scenarios={"base": 198000, "upside": 294000, "downside": 60000}),
        execution=DemoExecution(withdrawal_condition="2週連続で検証時間または予算上限を超えたら停止", resources=["週末6時間", "既存ノートPC", "合成チェックリスト"], roadmap=["1週目: 仮説整理", "2週目: 可逆な試験", "3週目: 継続/撤退判断"]),
        knowledge_assets=sources,
        decisions=[DemoDecision(id="decision-001", project_id="demo-project-001", decision="週末検証を採用", rationale="本業と家計の制約を守るため", evidence_ids=["demo-source-customer"])],
    )
