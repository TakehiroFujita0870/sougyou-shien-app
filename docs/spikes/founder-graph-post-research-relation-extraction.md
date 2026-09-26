# RP-SP-04: 調査後期待graphの表現可能性

## 結論

架空の調査後要約5件を先に作り、既存の`NodeType` / `RelationType`、根拠、概要章、`RelationAssertion`の保存契約へ写像するスパイクを追加した。focused testはインメモリadapterで全件成功。これは期待graphの表現・保存・再送可能性を示すだけで、会話からの自然言語検出、LLM抽出の精度、実調査、利用者受入を検証したものではない。

## 合成fixture

各fixtureには異なる8節見出しの架空調査後briefを持たせた。期待関係を支える具体的な架空事実と、その関係には結び付けないdistractor文は同じ関係対象章に書き、EvidenceのSourceRevision要約にも根拠文を保存する。

| fixture | 期待関係 | 根拠/訂正 |
| --- | --- | --- |
| `idea-reuses-asset` | Idea → Asset `REUSES` | 根拠付き。`REQUIRES_CAPABILITY`は非接続候補 |
| `person-contributes-to-idea` | Person → Idea `CAN_CONTRIBUTE_TO` | 提案状態、信頼度と期限を指定。別Organizationとの`WORKS_AT`は非接続候補 |
| `idea-serves-organization` | Idea → Organization `SERVES` | `COMPETES_WITH`は非接続候補 |
| `idea-addresses-claim` | Idea → Claim `ADDRESSES` | fixture内でEvidenceのclaim参照とrelationのClaim endpointを一致検査 |
| `same-family-correction` | Idea → Asset `REUSES` | 初期Run/briefには初版Evidenceのみを含む。後続で新Source/Evidenceを取得し、追加完了Runと新brief版を保存。更新章の新根拠だけに基づく後継assertionが同一familyを継承して旧版をsupersede |

fixtureと実行契約は`backend/tests/founder_graph_post_research_fixtures.py`および`backend/tests/test_founder_graph_rp_sp04_expected_graphs.py`にある。

## 既存契約で確認したこと

- 4種の期待predicateと3種のnegative候補は既存endpoint allowlistに適合する。
- `capture_source` → `capture_evidence`、承認済みResearchCampaign/完了ResearchRun、8節briefへの根拠ひも付け、`link_entities`の同一要求再送をインメモリで実行できる。Evidenceが参照するSourceRevisionの架空本文、該当brief章、期待関係を一緒に検査する。RelationAssertionのsource/target/predicate/status/confidence/expiryもfixture期待値と照合する。
- 同一target/predicateの訂正は、追加の完了Runと改訂briefを保存した後、low-level `save_relation_assertion`のCASで同じassertion familyに後継として保存できる。旧assertionを残し新assertionから`supersedes_id`を参照する。訂正をMCPから行う検査ではない。
- Facetは単独分類値として扱えるがFacet→Facet endpointは許可されず、domain Facetに`parent_id`もない。分類階層は現schemaで表現できない。

## 未解決の制約

- `link_entities`は生成関係を提案/推論状態で受け付けるが、訂正用`supersedes_id`やfamily CASを入力できない。訂正経路は現在adapterの直接APIであり、MCPの最小入口で完結しない。
- RelationAssertion保存時、Evidenceが同じbrief章に存在することやsource-groundedであることは検査されるが、Evidence.claim_idとClaim endpointの一致までは強制されない。テストはこの不整合を受け入れる現状を記録する。fixture自身の一致検査をこれの代替とはしない。
- 上記はschema/APIの次の判断事項として残す。今回、production schemaや抽出器は変更していない。

## 安全性と検査範囲

データは全てコード内で生成した架空fixtureで、外部通信・実アカウント・実会話・実調査を使わない。試験URLは予約済み`example.invalid`ドメインである。

実行: `uv run pytest -q backend/tests/test_founder_graph_rp_sp04_expected_graphs.py` — 8 passed。
