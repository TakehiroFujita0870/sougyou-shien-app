"""Fictional, post-research graph expectations for the RP-SP-04 spike."""

from dataclasses import dataclass


@dataclass(frozen=True)
class EntitySpec:
    key: str
    node_type: str
    name: str


@dataclass(frozen=True)
class EvidenceRef:
    key: str
    claim_key: str
    section_index: int | None
    summary: str


@dataclass(frozen=True)
class RelationSpec:
    key: str
    source_key: str
    target_key: str
    source_type: str
    target_type: str
    predicate: str
    evidence_key: str
    section_index: int
    status: str = "proposed"
    confidence: float | None = None
    expires_at: str | None = None


@dataclass(frozen=True)
class ExpectedGraph:
    fixture_id: str
    brief_sections: tuple[str, ...]
    entities: tuple[EntitySpec, ...]
    evidence_refs: tuple[EvidenceRef, ...]
    expected_relations: tuple[RelationSpec, ...]
    no_edges: tuple[RelationSpec, ...]
    distractors: tuple[str, ...]
    initial_relation: RelationSpec | None = None


_SECTION_NAMES = (
    "要約", "顧客と課題", "解決案", "市場と利用状況", "比較", "実現可能性", "リスク", "次の検証",
)


def _sections(topic: str, relation_fact: str, distractor: str, *, relation_section: int = 2,
              initial_fact: str | None = None) -> tuple[str, ...]:
    return tuple(
        f"{index}. {name} — 架空ケース「{topic}」。"
        + (f" 調査根拠: {relation_fact} 非接続候補: {distractor}" if index == relation_section else "")
        + (f" 初版根拠: {initial_fact}" if index == 1 and initial_fact else "")
        + " 内容は検証専用の創作で、実在情報ではない。"
        for index, name in enumerate(_SECTION_NAMES)
    )


def _claim(key: str = "claim", text: str | None = None) -> EntitySpec:
    return EntitySpec(key, "claim", text or f"架空の検証可能な主張 {key}")


def _evidence(key: str, claim_key: str = "claim", section: int = 2, summary: str = "架空の根拠") -> EvidenceRef:
    return EvidenceRef(key, claim_key, section, summary)


def _edge(key: str, source: str, target: str, source_type: str, target_type: str,
          predicate: str, evidence: str, section: int = 2, **kwargs: object) -> RelationSpec:
    return RelationSpec(key, source, target, source_type, target_type, predicate, evidence, section, **kwargs)


EXPECTED_GRAPHS = (
    ExpectedGraph(
        "idea-reuses-asset", _sections("小型展示キット", "試作で既存の折り畳み展示台が寸法適合し再利用された。", "展示台が近くに置かれていた写真だけでは利用関係を結ばない。"),
        (EntitySpec("idea", "idea", "小型展示キット案"), EntitySpec("asset", "asset", "再利用できる展示台"), _claim()),
        (_evidence("reuse-evidence", summary="折り畳み展示台は試作キットと寸法が合い、組立試験で再利用できた。"),),
        (_edge("reuse", "idea", "asset", "idea", "asset", "REUSES", "reuse-evidence"),),
        (_edge("not-required", "idea", "asset", "idea", "asset", "REQUIRES_CAPABILITY", "reuse-evidence"),),
        ("展示台が近くに置かれていた写真だけでは利用関係を結ばない。",),
    ),
    ExpectedGraph(
        "person-contributes-to-idea", _sections("地域向け試作会", "協力者は週末に試作品を組み立てる時間を提供できると回答した。", "同じ会話に団体名が出ても、雇用関係の根拠がなければ接続しない。"),
        (EntitySpec("person", "person", "架空の試作協力者"), EntitySpec("idea", "idea", "地域向け試作会案"),
         EntitySpec("organization", "organization", "架空の別団体"), _claim()),
        (_evidence("contribution-evidence", summary="協力者が期限付きで週末の試作組立時間を提供できると回答した。"),),
        (_edge("contribution", "person", "idea", "person", "idea", "CAN_CONTRIBUTE_TO", "contribution-evidence",
               status="proposed", confidence=0.72, expires_at="2099-01-01T00:00:00Z"),),
        (_edge("not-employed", "person", "organization", "person", "organization", "WORKS_AT", "contribution-evidence"),),
        ("同じ会話に団体名が出ても、雇用関係の根拠がなければ接続しない。",),
    ),
    ExpectedGraph(
        "idea-serves-organization", _sections("予約受付の改善", "架空団体が試行利用者となり、受付待ち行列の短縮を検証する。", "対象団体が利用者であることは競合を意味しない。"),
        (EntitySpec("idea", "idea", "予約受付改善案"), EntitySpec("organization", "organization", "架空の利用団体"), _claim()),
        (_evidence("service-evidence", summary="架空団体の受付担当が試行利用者となる合意をした。"),),
        (_edge("serves", "idea", "organization", "idea", "organization", "SERVES", "service-evidence"),),
        (_edge("not-competes", "idea", "organization", "idea", "organization", "COMPETES_WITH", "service-evidence"),),
        ("対象団体が利用者であることは競合を意味しない。",),
    ),
    ExpectedGraph(
        "idea-addresses-claim", _sections("作業手順の短縮", "CSV一括受付案は手入力転記で遅延するという主張への対処として検討された。", "別の主張に結び付く証拠をこの関係の根拠として流用しない。"),
        (EntitySpec("idea", "idea", "作業手順短縮案"), _claim(text="手入力転記により架空受付の処理が遅延する")),
        (_evidence("claim-evidence", summary="架空の試験記録で手入力転記が処理待ちを生むと確認された。"),),
        (_edge("addresses", "idea", "claim", "idea", "claim", "ADDRESSES", "claim-evidence"),),
        (_edge("claim-not-contradicted", "claim", "evidence", "claim", "evidence", "CONTRADICTED_BY", "claim-evidence"),),
        ("別の主張に結び付く証拠をこの関係の根拠として流用しない。",),
    ),
    ExpectedGraph(
        "same-family-correction", _sections("在庫見える化案", "改訂調査では試作棚センサーが同じ棚で再利用済みと確認された。", "旧説明を残しつつ、根拠を訂正して同じ関係familyの後継版にする。", relation_section=5, initial_fact="初版では同型センサーを棚で再利用できる見込みと記録した。"),
        (EntitySpec("idea", "idea", "在庫見える化案"), EntitySpec("asset", "asset", "試作棚センサー"), _claim()),
        (_evidence("initial-evidence", section=1, summary="初回の架空試作記録では同型センサーの再利用を見込みとした。"),
         _evidence("corrected-evidence", section=5, summary="改訂版架空記録で同じ試作棚へのセンサー再利用を確認した。")),
        (_edge("corrected-reuse", "idea", "asset", "idea", "asset", "REUSES", "corrected-evidence", section=5),),
        (_edge("not-required", "idea", "asset", "idea", "asset", "REQUIRES_CAPABILITY", "corrected-evidence", section=5),),
        ("旧説明を残しつつ、根拠を訂正して同じ関係familyの後継版にする。",),
        initial_relation=_edge("initial-reuse", "idea", "asset", "idea", "asset", "REUSES", "initial-evidence", section=1),
    ),
)
