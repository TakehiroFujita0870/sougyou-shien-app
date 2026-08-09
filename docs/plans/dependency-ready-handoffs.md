# DEPENDENCY_READY ハンドオフ計画

最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

要望: merge済みPRが後続部門に提供する契約を、不揮発なイベントで直接引き渡す。

ゴール: 統合部がnext_dependenciesを検出した場合、CEO室へのMERGEDと同時に次担当部をDEPENDENCY_READYで起動し、送信成功までhandoffを未完了として扱う。

成功指標: 運用正本とAGENTS.mdに発火条件、必須payload、冪等キー、直接起動条件、CEO室へDECISION_REQUIREDを送る限定条件、統合部プロファイルが記録される。

## ユーザーストーリーと受け入れ条件

### US-1

As a 統合・リリース管理部, I want merge済みの依存契約を次担当部へ直接渡したい, so that 後続作業が会話履歴や定期監視を待たず開始できる。

Given: merge後のnext_dependenciesに次担当部が明記されている
When: 統合部がMERGEDを送る
Then: 同じsource merge SHAとtarget departmentを冪等キーにしてDEPENDENCY_READYを送信し、成功確認までhandoffを未完了とする。

### US-2

As a 次担当部, I want source PRの契約と禁止境界を受け取りたい, so that owner隔離や削除伝播を壊さず後続PRを作れる。

Given: DEPENDENCY_READYを受信している
When: 次担当部が設計または実装を開始する
Then: source PR/merge SHA、提供契約、次Issue/目的、受入条件、変更禁止境界、検査、owner task、next_actionを確認できる。

### US-3

As a 管理タスク, I want 未割当またはCEO判断が必要なhandoffだけを受け取りたい, so that 通常のCI失敗やP1/P2でCEO室を過剰通知しない。

Given: 次担当が未割当、優先順位競合、新scope、またはCEO境界に該当する
When: 統合部が次担当を確定できない
Then: 統合部はDECISION_REQUIREDをCEO室へ送る。通常のCI失敗とP1/P2は担当部と統合部で解決する。

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| Q-1 | DEPENDENCY_READY受信後のIssue採番方式 | 管理タスク | 次の新scope発生時 |

## スコープ外

- 外部キュー、Webhook、Bot、GitHub Actionsの定期実行
- CEO室への通常PR_READY通知
- 統合部プロファイルの無断フォールバック
- mainへの直接push

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-1 | DEPENDENCY_READYの発火規則とpayload | 検査: 必須11項目と冪等キーをoperations文書で確認 | 既知 |
| T-2 | merge後handoffの完了条件とDECISION_REQUIRED境界 | 検査: MERGED節とAGENTS.mdを確認 | 既知 |
| T-3 | 統合部プロファイル規約 | 検査: `gpt-5.6-terra / medium` とBLOCKED条件を確認 | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| 依存handoff | merge成功後に統合部が次担当部を直接起動する | CEO室経由の通常通知は遅延と過剰通知を生む | DEPENDENCY_READYを正本化する |
| 完了条件 | 送信成功確認までhandoffを未完了にする | MERGED送信だけでは次担当が起動したことを保証できない | 配信結果を統合部が記録する |
| 統合部プロファイル | gpt-5.6-terra / mediumを固定する | 無断の低品質プロファイル変更はレビュー品質を不安定化する | 利用不能時のみBLOCKEDを管理タスクへ送る |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | 初版 | PR #92の依存契約handoff欠落を恒久化 | T-1からT-3 |
