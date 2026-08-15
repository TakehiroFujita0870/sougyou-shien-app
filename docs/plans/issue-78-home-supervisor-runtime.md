# Issue #78 Home supervisor runtime plan

## 要望 / ゴール / 成功指標

要望: HomeのDots. AIを、local context snapshotに基づくportfolio supervisor入口にする。

ゴール: deterministicな提案を事実・推論・操作として表示し、明示確認後だけ端末内に保存する。

成功指標: F5後も会話と提案を復元し、raw/token/secretとfetchが0件である。

## ユーザーストーリーと受け入れ条件

### US-1
As a 利用者, I want Homeで次の検討を選ぶ, so that portfolio全体の作業を整理できる。

Given: allowlist済みHome snapshotがある
When: ideation、profile、project、candidateの入力を送信する
Then: fact、inference、actionを区別したlocal proposalが表示される。

### US-2
As a 利用者, I want 提案を確認してから保存する, so that AIが勝手に状態を変えない。

Given: proposalが表示されている
When: 確認を選ぶ
Then: proposalはconfirmedとして端末内に保存される。

### US-3
As a 利用者, I want F5後に再開する, so that 会話と未確認proposalを失わない。

Given: local conversationが保存されている
When: Homeをremountする
Then: messages、proposals、confirmed状態が復元される。

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| Q-78-1 | confirmed actionの実Project/Knowledge接続先 | CEO | 後続runtime assignment |

## スコープ外

- 外部AI、fetch、API、PII、独立chat route
- App shell、WorkspaceShell、shared style、nav、token
- Project/Knowledgeへの実永続接続

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-78-1 | HomeSupervisorとlocal repository | 検査: component test | 既知 |
| T-78-2 | Home最小接続 | 検査: App acceptance test | 類推可能 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| action model | local deterministic proposal | 外部modelは送信境界を越えるため却下 | explicit confirmationを維持 |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | 初版 | CEO assignment | T-78-1、T-78-2 |
