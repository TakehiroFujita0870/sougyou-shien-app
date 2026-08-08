# 意思決定記憶の保存・検索API 計画

最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

### 要望原文

> PR #26で追加されたdecision_records/decision_observationsの所有者境界を使い、意思決定記憶の保存・検索APIを1 PRで実装してください。

### ゴール

認証情報なしでも、local/fake repository上で所有者境界を保った意思決定の保存・検索API契約を完成させる。

### 成功指標

- APIテストで前回判断、新根拠、失効済み、別ユーザー拒否の4ケースを検証する。
- API入力の`owner_id`ではなく、local fake認証コンテキストだけから所有者を確定する。

## ユーザーストーリーと受け入れ条件

### US-01 意思決定を保存する

As a アイデアを検討するユーザー, I want 判断、理由、根拠、採否、valid_from、supersedesを保存したい, so that 判断の前提と後継関係を後から確認できる。

Given: local fake認証コンテキストにユーザーIDがあり、同じアイデアの入力が有効である

When: `POST /v1/decisions`を呼ぶ

Then: APIは所有者をリクエスト本文から受け取らず、保存済みの判断と観測を返す

### US-02 過去判断と新根拠を検索する

As a 継続利用するユーザー, I want 過去判断と再検討対象の根拠を検索したい, so that 新しい事実を理由と区別して判断できる。

Given: 同じアイデアに過去判断と`reconsider`の新根拠がある

When: `GET /v1/decisions/search`を呼ぶ

Then: 過去判断、理由、根拠、採否、valid_from、supersedesが結果に含まれる

### US-03 失効判断を確認する

As a 継続利用するユーザー, I want 失効済みの判断も確認したい, so that 過去指摘を機械的に隠さずに前提の変化を評価できる。

Given: 検索語に一致する失効済みの判断がある

When: 検索APIを呼ぶ

Then: 結果に失効状態を含めて返し、検索結果から除外しない

### US-04 所有者境界を守る

As a ユーザー, I want 他ユーザーの意思決定を取得も後継指定もできない, so that 個人の判断履歴が分離される。

Given: ユーザーAが保存した判断がある

When: ユーザーBが検索するか、その判断を`supersedes_id`に指定して保存する

Then: 検索結果は空になり、後継指定は404で拒否される

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| Q-01 | Supabase Auth接続時の認証コンテキスト変換方式 | CEO | release-gate #31の実装前 |

## スコープ外

- Supabase Auth、実DB、実ユーザーデータ、認証情報、外部接続。
- UI、ResearchSource、既存migration、モデルカタログの変更。
- 過去指摘の機械的な非表示、LLMによる判断生成。
- 意思決定の更新・削除APIと本番検索インデックス。

## タスク

| ID | 成果物 | 完了判定 | 不確実性 |
| --- | --- | --- | --- |
| T-01 | Decision Record / Observationのlocalドメインと所有者限定fake repository | 検査: APIテストが他所有者の検索を空、後継指定を404にする | 類推可能 |
| T-02 | 保存・検索FastAPI契約 | 検査: APIテストが前回判断、新根拠、失効済みの結果を確認する | 既知 |
| T-03 | 計画・セルフレビュー | 検査: `npm run test`、`npm run build`、`npm run build-storybook`、`uv run pytest`、`git diff --check`が成功する | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| 所有者の取得 | `X-Local-Owner-Id`をlocal fake認証コンテキストとして依存性注入し、JSON本文の所有者を受けない。将来Supabase Auth実装へ置換可能 | `owner_id`をJSON本文へ置く案は偽装可能なため却下 | 本番接続前にrelease-gate #31で認証依存性を置換する |
| 永続化 | インメモリrepositoryをポートとして分離する。認証待ちでも成功・失敗・所有者境界の契約を完成できる | Supabase SDKを暫定接続する案は認証情報と実データ接続を必要とするため却下 | 本番repositoryは同じポートを実装する |
| 失効判断 | `status=expired`の記録も検索結果に返す | 失効済み記録を除外する案は過去判断を隠すため却下 | 消費側が状態を表示して再検討する |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | 初版。Issue #13のlocal/fake API契約を定義 | Supabase Auth未接続でも所有者境界を検証するため | T-01からT-03 |
