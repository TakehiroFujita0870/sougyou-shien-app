# Python runtime lock collection gate 計画

最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

要望: CPython 3.14.3 で locked sync 後の pytest collection failure を最小修正する。

ゴール: typing-extensions を lock 解決対象として明示し、pydantic_core の Sentinel import を満たす。

成功指標: `uv sync --locked --all-groups --link-mode=copy` 後に `uv run pytest` が collection error なく完走する。

## ユーザーストーリーと受け入れ条件

### US-PY-1
As a developer, I want the locked Python environment to collect tests on CPython 3.14.3, so that backend quality gates run.

Given: CPython 3.14.3 と lockfile がある。
When: locked sync の後に pytest を実行する。
Then: typing_extensions.Sentinel の import error は発生せず、テストが完走する。

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| なし | 未決事項なし | - | - |

## スコープ外

- frontend、App、Shell、style、API、auth の変更。
- 外部サービス、個人情報、#62 の変更。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-PY-1 | typing-extensions の直接依存と lock 更新 | 検査: locked sync と pytest | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| 修正方法 | typing-extensions を直接依存にして全対象 Python で lock する。 | Python 上限を 3.13 に下げる案は対応済み 3.14 を不要に排除する。 | 採用 |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | 初版 | collection gate を最小範囲へ固定 | T-PY-1 |
