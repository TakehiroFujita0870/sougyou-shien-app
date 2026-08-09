# Issue #54 plan persistence prerequisite 計画

最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

要望: Free/Standard の plan と model/reasoning 選択を local storage から安全に復元する。

ゴール: App wiring を変更せず、storage-backed repository が一回の hydration、正規化、保存失敗時の保護を提供する。

成功指標: Standard と model/reasoning が再生成後も復元され、破損・不正値・load/save failure が安全な値に正規化される。

## ユーザーストーリーと受け入れ条件

### US-54-1
As a Free or Standard user, I want my plan and model choice persisted locally, so that F5 retains my selection.

Given: 有効な plan/model/reasoning を save する。
When: repository を再生成して load する。
Then: 同じ正規化済み subscription を返す。

### US-54-2
As a user, I want corrupt local storage normalized safely, so that invalid data cannot escape the repository boundary.

Given: JSON破損または許可外の selection が storage にある。
When: repository が hydrate する。
Then: plan/model/reasoning は許可された default に正規化される。

### US-54-3
As a user, I want load failures not to overwrite a good local state, so that transient storage errors are recoverable.

Given: storage read または write が失敗する。
When: repository が load/save する。
Then: load は default を返し、save failure は現在の subscription を変更しない。

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| なし | 未決事項なし | - | - |

## スコープ外

- App.jsx wiring、shell/style、plan card redesign。
- payment、pricing change、外部サービス、個人情報。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-54-1 | storage-backed local plan repository | 検査: repository 契約テスト | 既知 |
| T-54-2 | corrupt/failure/single-hydration tests | 検査: repository 契約テスト、full frontend test | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| storage boundary | repository が JSON parse、allowlist normalization、例外を閉じ込める。 | App が直接 localStorage を読む案は ownership と failure handling を分散する。 | 採用 |
| write failure | save 前の current state を維持し、例外を返す。 | 失敗を成功扱いして state を更新する案は F5 と表示を不一致にする。 | 採用 |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | 初版 | #54 の repository-only prerequisite を固定 | T-54-1 から T-54-2 |
