# Issue #81 プロフィール hydration 修正計画

最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

要望: 完了済みプロフィールの再読込で入力を再開せず、読込失敗時に保存済み値を空で上書きしない。

ゴール: App/account 境界で一回だけプロフィールを hydration し、読込世代と mount 状態を確認した結果だけを画面へ反映する。

成功指標: 完了、null、途中保存、失敗からの再試行、同一 mount の一回読込、unmount 後と古い読込結果の無視を契約テストで観測できる。

## ユーザーストーリーと受け入れ条件

### US-81-1

As a completed-profile user, I want reload to preserve completion, so that the interview does not reopen.

Given: status が completed の保存済みプロフィールがある。
When: App が hydration を完了する。
Then: 入力フォームは表示されず、更新ボタンだけが表示される。

### US-81-2

As a new or returning user, I want the interview to open only after my profile is read, so that saved progress is not replaced with empty data.

Given: profile が null または in_progress である。
When: hydration が成功する。
Then: 読込中には入力フォームを表示せず、完了後に対応する初期値でフォームを表示する。

### US-81-3

As a user with a failed local read, I want a safe retry, so that I cannot overwrite saved data with an empty profile.

Given: profile repository の load が失敗する。
When: エラー画面で再試行する。
Then: 読込エラー中は入力と save を表示せず、成功した retry の結果だけを表示する。

### US-81-4

As an application user, I want stale hydration results ignored, so that late reads cannot change the current screen.

Given: retry または unmount の前に load が保留中である。
When: 古い load が後から完了する。
Then: 古い結果は hydration state とフォーム表示を変更しない。

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| なし | 未決事項なし | - | - |

## スコープ外

- 外部 OAuth、Supabase、外部 API、個人情報送信。
- subscription、model、account の個別 hydration 実装。
- App.jsx と shared style の同時変更。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-81-1 | request 世代と unmount guard を持つ local hydration hook | 検査: `npm run test -- --run src/App.profile-hydration.test.jsx` | 既知 |
| T-81-2 | completed、null、in_progress、error retry、single-load、late result の契約テスト | 検査: `npm run test -- --run src/App.profile-hydration.test.jsx` | 既知 |
| T-81-3 | future subscription/model/account 用の hydration 不変条件 | 検査: この計画の ADR をレビュー | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| hydration 所有者 | App/account 境界が repository を一回だけ読む。フォームは初期値だけを受け取る。 | フォーム自身が load する案は親子間で結果が競合する。 | 採用 |
| stale 結果 | request 世代と mount guard が一致する結果だけを反映する。 | Promise 完了順に無条件で反映する案は retry と unmount の画面を壊す。 | 採用 |
| 横展開不変条件 | subscription、model、account も loading、ready、error の三相と一回読込、retry 世代、unmount guard を守る。個別実装は後続 Issue とする。 | profile 専用の例外規則を増やす案は失敗経路を再発させる。 | 採用 |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | 初版 | #81 の hydration 受入条件を固定 | T-81-1 から T-81-3 |
