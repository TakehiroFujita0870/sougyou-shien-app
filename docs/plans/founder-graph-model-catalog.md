# Founder Graph モデルカタログ・プロバイダー境界 計画

最終検証日: 2026-09-22

## 要望 / ゴール / 成功指標

### 要望

「Founder Graph pivot bounded task: implement a small backend model catalog/provider abstraction for logical Luna key, following docs/operations/model-lifecycle.md and project rules. No external API calls or secrets. Add tests and a plan doc if needed. Work only on model catalog-related files; report files/tests.」

### ゴール

Dots backendの製品runtimeがモデルIDを直接参照せず、論理キー`luna`からカタログとプロバイダー境界を解決できる状態にする。

### 成功指標

カタログの必須属性、Lunaの既定解決、未知・無効モデルの失敗、未設定プロバイダーの明示的な利用不能、プロバイダー差し替え契約をローカルテストだけで検証できる。

## ユーザーストーリーと受け入れ条件

### US-MC-1

As a Founder Graph backend developer, I want to resolve a provider through the logical Luna key, so that model IDs remain centralized and future provider replacement does not change domain code.

Given: the default catalog contains one enabled entry whose logical key is `luna`

When: a caller resolves the default logical model and asks the provider registry for its adapter

Then: the catalog entry exposes the lifecycle fields, the snapshot identifies the logical entry, and the registry returns the adapter without opening a network connection.

Given: a caller supplies an unknown or disabled logical key

When: the caller resolves the model

Then: a typed catalog error identifies the recoverable lookup failure and no provider method is called.

Given: the Luna provider has no configured local adapter

When: a caller invokes the provider boundary

Then: a typed unavailable error is raised without reading a secret or making an external request.

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |

## スコープ外

- 外部AI SDK、HTTP client、APIキー、秘密管理、実データ送信。
- Lunaの公式provider/model ID、価格、embedding対応可否の決定。
- FastAPI endpoint、MCP tool、Neo4j persistence、Frontend catalogの移行。
- Free / Standard / Proの料金権限とモデル選択UI。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-MC-1 | backend model catalog value object、Luna default、catalog lookup | 検査: `uv run pytest backend/tests/test_model_catalog.py -q` が通り、必須フィールドと未知・無効キーの挙動を確認する | 既知 |
| T-MC-2 | provider protocol、registry、unconfigured adapter、snapshot | 検査: `uv run pytest backend/tests/test_model_catalog.py -q` が通り、差し替えadapterと未設定エラーを確認する | 既知 |
| T-MC-3 | 計画と実装のセルフレビュー | 検査: `git diff --check`、変更ファイルの秘密語スキャン、対象テストを実行する | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| ADR-MC-1 論理キー | `luna`を製品runtimeの唯一の初期論理キーとし、provider/model IDはcatalog entryに隔離する | 呼出元が`gpt-*`やClaudeの文字列を直接持つ案は、provider交換と評価時のsnapshotを壊すため却下 | Dotsの意味処理は`luna`を解決してからadapterを呼ぶ |
| ADR-MC-2 未設定provider | networkを持たない`UnconfiguredModelProvider`を既定にし、利用時はtyped unavailable errorを返す | Fake responseを既定で返す案は実処理と評価経路を混同するため却下 | テストは明示したin-memory adapterだけを差し込む |
| ADR-MC-3 カタログ形状 | model-lifecycle.mdの`logical_key`、`provider`、`model_id`、`plans`、`reasoning_modes`、`capabilities`、`cost_class`、`enabled`、`is_default`をimmutable entryへ集約する | endpointや各domain moduleへ属性を分散する案は更新時の整合性を失うため却下 | catalog lookupは一つの境界から提供する |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-09-22 | 初版。Luna logical keyとprovider boundaryの最小契約を定義 | Founder Graph pivotのbackend実装をモデルライフサイクル規約へ接続するため | T-MC-1からT-MC-3 |
