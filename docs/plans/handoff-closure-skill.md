# Handoff closure skill 計画

最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

要望: 次工程を持つ成果がfinal回答だけで切断されないよう、送達と受領確認を単一Skillで必須化する。

ゴール: 送信元が同一turnで次担当を起動し、受領または失敗を確認するまで未完了を維持できる。

成功指標: Skill、INDEX、AGENTSの最小差分がhandoffの送達、受領、失敗、自己送信禁止、CEO handshakeを観測可能に指示する。

## ユーザーストーリーと受け入れ条件

### US-1 PR_READY

As a 実装部門, I want PR_READYを統合部へ送達確認したい, so that reviewがfinal回答で止まらない。

Given: successor taskとhead SHAが確定している。
When: PR_READYを送る。
Then: 同一turnでidempotency keyを付け、receiverのHANDOFF_ACCEPTEDまたはreview開始を確認する。

### US-2 レビュー差し戻し

As a 統合部, I want REVIEW_CHANGES_REQUESTEDを作者へ受領確認付きで渡したい, so that 修正がidleにならない。

Given: reviewerがP1またはP2を検出した。
When: 差し戻しを送る。
Then: 作者のHANDOFF_ACCEPTEDまたはactive修正状態を確認するまでreviewを完了扱いにしない。

### US-3 送達失敗

As a 送信者, I want failed deliveryを明示したい, so that次工程の欠落を隠さない。

Given: targetが受領確認を返さない。
When: read/waitが失敗またはtimeoutする。
Then: HANDOFF_FAILEDにtarget、event、idempotency key、retry状態を記録し、送信元を未完了に保つ。

### US-4 自己送信禁止

As a 統合部, I want self-cycleを防ぎたい, so that独立レビューが失われない。

Given: senderとtargetが同一taskである。
When: handoffを開始しようとする。
Then: 送信せず別の責任者またはBLOCKEDを選ぶ。

### US-5 MERGEDとCEO

As a 統合部, I want merge後のCEO経路を維持したい, so thatポートフォリオ決定権を越えない。

Given: mergeとsmokeが成功している。
When: MERGEDを送る。
Then: dependency deliveryを確認し、CEOへはMERGED{org_health}だけを送りGO_ON/CHANGE/BLOCKを待つ。

## 質問リスト

なし。イベント名と受領状態は既存運用で決定済み。

## スコープ外

- handoff自動送信script、外部サービス、GitHub PR更新、既存実装PRの変更。
- department-handoffsの重複手順、README、assets、references、INSTALL、CHANGELOG。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-1 | handoff-closure SKILL.md | 検査: quick_validate.py | 既知 |
| T-2 | INDEXとAGENTSの入口 | 検査: rgでSkill参照を確認 | 既知 |
| T-3 | dry-run forward test記録 | 検査: live task/PRを変更しないシナリオで受領前final禁止を確認 | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| 形式 | 命令形の単一SKILL.md | scriptは今回のdry-runに不要 | 採用 |
| 正本 | Skillを実行手順、既存handoffsを組織運用の正本に維持 | 重複説明は更新ずれを生む | 採用 |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | 初版 | final回答によるhandoff切断の再発防止 | T-1からT-3 |
