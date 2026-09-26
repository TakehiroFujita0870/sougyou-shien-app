# IdeaBriefVersionのResearchRun参照 配送計画
最終検証日: 2026-09-26

## 要望 / ゴール / 成功指標
要望: 既存のIdeaBriefVersionに、後続ResearchRunとの参照を安全に保持する値を追加する。
ゴール: 旧形式のbriefを空参照のまま受け入れ、Run参照を不変なtupleとして扱い、改訂時に保持・更新・解除できるようにする。
成功指標: 空tuple既定、可変listからtupleへの正規化、改訂時の保持/更新/解除、および空白・不正型・重複・長さ・件数超過の拒否を専用テストで確認する。

## ユーザーストーリーと受け入れ条件
### US-IB-01
As a local owner, I want an idea brief to carry bounded references to research runs, so that old briefs remain compatible and revisions can update their linked runs explicitly.
Given: 既存のIdeaBriefVersionを構築または改訂する。
When: research_run_idsを省略、指定、または空にする。
Then: 新規/旧形式は空tupleになり、list入力はtupleへ正規化され、改訂では省略時に保持・指定時に更新・空指定時に解除される。

### US-IB-02
As a local owner, I want malformed research references rejected at the value boundary, so that a brief cannot carry ambiguous or unbounded run IDs.
Given: research_run_idsに空白、不正型、重複、201文字以上、または33件以上がある。
When: IdeaBriefVersionを構築または改訂する。
Then: IdeaBriefValidationErrorが発生し、既存の不変なBrief契約は変わらない。

## 質問リスト
| ID | 質問 | 決定者 | 期限 |
|---|---|---|---|
| なし | 今回の受入契約は確定済み | — | — |

## スコープ外
- IdeaBriefVersionの既存8章、版系譜、共有範囲契約の新設・変更。
- Neo4jやメモリ上の永続化、原子的なRun/Campaign更新。
- ResearchCampaignの取消・時刻検査・調査完了判定。
- MCP/API/stdio、外部検索、ChatGPT接続、runtime変更。
- Evidence、Source、RelationAssertionの保存経路。

## タスク
| ID | 成果物 | 完了判定（検査:） | 不確実性 |
|---|---|---|---|
| T-IB-01 | research_run_idsの契約テスト | `uv run pytest backend/tests/test_idea_brief.py -q` | 既知 |
| T-IB-02 | 既存値モデルへの限定的なRun参照追加 | T-IB-01および`uv run pytest backend/tests -q` | 既知 |

## ADR
| 判断 | 選択と理由 | 却下案と理由 | 結果 |
|---|---|---|---|
| 研究Run参照 | 既存frozen dataclassへ空tuple既定のresearch_run_idsを加え、改訂時は省略=保持・明示空=解除 | model構築時の外部registry検索は純粋な値検証を壊す | Runの存在・所有者・完了・認可は後続research gateで検証する |

## 変更履歴
| 日時 | 変更 | 理由 | 影響タスク |
|---|---|---|---|
| 2026-09-26 | 初版 | mainに存在するIdeaBriefVersionへResearchRun参照の互換値契約を追加 | T-IB-01,T-IB-02 |
