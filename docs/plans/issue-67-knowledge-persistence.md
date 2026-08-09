# Issue #67 Knowledge metadata persistence 計画

最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標
要望: document metadata と extracted-text/index lifecycle marker を F5 後も安全に保持する。
ゴール: owner/space/deletion 境界を持つ binary-free local repository を提供する。
成功指標: add/list/reload/delete、owner isolation、corrupt quarantine、read failure 保護を契約テストで観測する。

## ユーザーストーリーと受け入れ条件
### US-67-1
As a workspace owner, I want document metadata persisted locally, so that reload retains searchable lifecycle state.
Given: owner/space付き metadata を add する。
When: repository を再生成して load する。
Then: binary content なしで metadata と lifecycle marker が復元される。
### US-67-2
As a user, I want private and deleted records isolated, so that another owner cannot list or reference them.
Given: owner A/B と deleted metadata がある。
When: 各 owner が list または delete する。
Then: owner/space scope 内の active metadata だけが返る。

## 質問リスト
| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| なし | 未決事項なし | - | - |

## スコープ外
- binary contents、upload UI、App/Shell/style、embeddings、external storage、Supabase、AI calls。

## タスク
| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-67-1 | schema-versioned metadata repository | 検査: repository 契約テスト | 既知 |
| T-67-2 | privacy/deletion/corrupt/late-load tests | 検査: repository 契約テスト | 既知 |

## ADR
| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| storage | localStorage に JSON metadata のみ保存する。 | binary や外部 storage は scope 外かつ漏えい面を増やす。 | 採用 |
| deletion | tombstone manifest を保存し、list では active のみ返す。 | 即時物理削除は stale reference を追跡できない。 | 採用 |

## 変更履歴
| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | 初版 | #67 prerequisite scope を固定 | T-67-1 から T-67-2 |
