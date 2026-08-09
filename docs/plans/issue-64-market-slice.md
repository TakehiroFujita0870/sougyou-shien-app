# Issue #64 市場・3種競合・勝ち筋 第一slice
最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標
市場根拠と直接・間接・代替競合、潜在参入リスク、本人判断の勝ち筋・機会をlocal/fake契約で分離する。外部Web/APIを使わず、既存market reportの後方互換を保つ。

## ユーザーストーリーと受け入れ条件
### US-64-01
As a 事業案を比較する利用者, I want 3種競合と潜在参入を分けたい, so that比較対象と将来リスクを混同しない。
Given: reportに競合と潜在参入リスクを入力する
When: deterministic local reportを保存する
Then: direct、indirect、alternativeは別categoryで返り、potentialはcompetitorとして受け付けない。
### US-64-02
As a 利用者, I want勝ち筋・機会を本人判断として保存したい, so thatAI推論やEvidenceと混同しない。
Given: Evidence IDを参照する本人判断を入力する
When: reportを生成する
Then: evidence、ai_inference、owner_judgmentsが別フィールドで返る。

## スコープ外
- Web検索、特許API、外部AI、画像生成、金融接続、UI/App.jsx。
- 顧客ヒアリング原文や匿名化処理、project横断grantの新規実装。

## タスク
| ID | 成果物 | 完了判定（検査:） | 不確実性 |
|---|---|---|---|
| T-64-01 | 後方互換market report contract | 検査: 3種分類、potential拒否、judgment分離、Evidence ID検証、owner隔離のpytest | 類推可能 |

## ADR
| 判断 | 選択と理由 | 却下案と理由 | 結果 |
|---|---|---|---|
| ADR-64-01 | 既存Pydantic market reportを拡張し、任意フィールドで後方互換を維持する | 新endpoint・UI配線は既存利用者とUI部の変更範囲を広げるため却下 | local/fake APIで第一sliceを検証する |
| ADR-64-02 | competitor categoryはdirect/indirect/alternativeのLiteral、potentialは別モデル、judgmentはowner入力のみ | 1配列へ混在させる案は比較対象と将来リスクを混同するため却下 | Evidence IDは同一request集合で決定的に検証する |

## 変更履歴
| 日時 | 変更 | 理由 | 影響タスク |
|---|---|---|---|
| 2026-08-09 | 初版 | Issue #64第一sliceをlocal契約へ分割 | T-64-01 |
