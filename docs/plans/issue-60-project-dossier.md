# Issue #60 採用project dossier契約 計画
最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

要望: 採用済みprojectを「どんな事業」「市場はある」「競合は誰」「利益はでる」「実現できる」の5問で読める、決定的local/fake dossier assemblerを提供する。

ゴール: 市場・競合、unit economics、低リスク実行、根拠の既存契約を重複実装せずに組み立て、未確認・反対根拠・本人判断を明示する。

成功指標: 同じ入力は同じdossierを返し、別ownerの市場レポートは404、欠損sectionと相反根拠は観測可能なresponseになる。

## ユーザーストーリーと受け入れ条件

### US-60-08 5問で採用projectを読む

As a project owner, I want one local dossier with five plain-language questions, so that I can compare the current business hypothesis without navigating separate calculations.

Given: ownerがproject説明、market report、3 scenario unit economics入力、実行計画入力を持つ。
When: dossier endpointを取得する。
Then: 「どんな事業」「市場はある」「競合は誰」「利益はでる」「実現できる」の5 sectionが決定的な順序で返る。

### US-60-09 根拠と判断を区別する

As a project owner, I want facts, AI inference, and owner decisions separated with locators, so that I do not mistake an inference for evidence.

Given: market reportにsupporting、counter、unverified evidence、AI inference、owner judgmentがある。
When: dossierを組み立てる。
Then: source IDとlocatorを含むfacts、AI inference、owner decisions、contradictory evidenceが別fieldsで返る。

### US-60-10 未確認を読む

As a project owner, I want missing inputs marked as unconfirmed, so that the dossier does not fabricate completeness.

Given: market report、財務入力、または実行計画入力のいずれかがない。
When: dossierを組み立てる。
Then: 該当sectionは`unconfirmed`となり、missing reasonを返し、銀行または金融機関の推薦を返さない。

### US-60-11 所有者境界を守る

As a project owner, I want another owner's market report rejected, so that a local dossier cannot reveal another owner's evidence.

Given: owner Aがmarket reportを保存し、owner Bがそのreport IDを指定する。
When: owner Bがdossier endpointを呼ぶ。
Then: endpointは404を返し、owner Aの根拠、推論、判断を返さない。

## スコープ外

- UI、App.jsx、export、外部調査、外部API、外部AI、実金融機関接続。
- 既存market report、unit economics、execution planの計算式または保存契約の変更。
- PII、銀行名、口座、残高、認証情報の取得、保存、送信。
- DB migration、RLS、実project永続化、shared knowledge lookup。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-60-08 | `project_dossier.py`の決定的assembler | 検査: 同一入力のresponse一致、5 section順、欠損・相反根拠のpytest | 既知 |
| T-60-09 | `/v1/projects/{project_id}/dossier` local/fake endpoint | 検査: owner A/Bの404隔離、X-Local-Owner-Id欠損401のpytest | 類推可能 |
| T-60-10 | API契約テストと計画 | 検査: `pytest backend/tests/test_project_dossier_api.py`、`git diff --check` | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| 組立方式 | `market_report`、`calculate_plan`、`evaluate_execution_plan`を呼び出し、dossierは表示用の決定的組立だけを行う。 | 各計算式をdossierへ複製する案は計算契約の乖離を生むため却下。 | 既存domain契約が唯一の計算源となる。 |
| 未確認表示 | 欠損入力はsection statusとmissing reasonで返す。 | 推測した本文または0値で埋める案は本人判断と仮説を混同させるため却下。 | 未確認を明示する。 |
| 根拠境界 | evidenceのID・locator・excerptをfactsに限定し、AI inferenceとowner judgmentを別fieldにする。 | 結論文へ根拠・推論・本人判断を混在させる案は追跡不能なため却下。 | 出典追跡と判断区分を維持する。 |
| 所有者境界 | market reportは固定principalでrepositoryから取得し、request由来owner IDを持たない。 | report responseをclientから渡す案は他ownerの本文注入・再表示を防げないため却下。 | local owner header経由だけで参照する。 |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | Issue #60 dossier first sliceを作成 | 5観点の既存domain契約を1つのowner-scoped APIへ組み立てるため | T-60-08〜10 |
| 2026-08-09 | project/report一致と鮮度状態を追加 | 独立レビューで同一owner内のproject混在と更新時刻不明の扱いを指摘されたため | T-60-08〜10 |
