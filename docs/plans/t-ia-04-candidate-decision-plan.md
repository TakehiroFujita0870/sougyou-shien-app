# T-IA-04 conversation candidate decision plan
最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標
会話から提示された候補を、保存前に採用・保留・理由付き却下から選べるようにする。候補の3状態と却下理由がF5後も復元されることを成功指標とする。

## ユーザーストーリーと受け入れ条件
### US-1
As a user, I want to decide a candidate explicitly, so that no idea is promoted without my confirmation.
Given: a candidate preview is visible
When: I choose adopt, hold, or reject
Then: the selected state is persisted and only adopt marks project/knowledge promotion.

### US-2
As a user, I want rejection to be explainable, so that the system can retain decision history.
Given: a candidate preview is visible
When: I choose reject without a reason
Then: persistence is blocked and a reason prompt is shown.

### US-3
As a returning user, I want decisions restored, so that F5 does not lose my workflow.
Given: candidate decisions were saved locally
When: the workspace hydrates after reload
Then: adopted, held, rejected states and rejection reason are displayed.

## 質問リスト
| ID | 質問 | 決定者 | 期限 |
|---|---|---|---|
| Q-1 | Project/Knowledgeの実永続先は別ASSIGNMENTで接続するか | CEO | runtime接続前 |

## スコープ外
- App shell、WorkspaceShell、共有styles、nav、独立chat route
- 外部AI、fetch、Supabase、実データ送信
- Design部の共通UI primitive

## タスク
| ID | 成果物 | 完了判定（検査:） | 不確実性 |
|---|---|---|---|
| T-IA-04-R | 候補状態repository拡張 | 検査: candidate decision unit tests | 既知 |
| T-IA-04-Q | 採用/保留/却下UI | 検査: component keyboard and a11y tests | 既知 |
| T-IA-04-F | F5復元 | 検査: hydration persistence test | 既知 |

## ADR
| 判断 | 選択と理由 | 却下案と理由 | 結果 |
|---|---|---|---|
| 状態表現 | candidate.status と rejectionReasonを同一候補に保持 | 別storageは同期漏れを増やす | local repositoryで履歴を復元 |
| promotion境界 | adoptのみ promotedTo を設定 | hold/rejectの自動project化は意図に反する | project/knowledge接続は後続assignment |

## 変更履歴
| 日時 | 変更 | 理由 | 影響タスク |
|---|---|---|---|
| 2026-08-09 | 初版 | T-IA-04 assignment | 全て |
