# 横断調査オーケストレーターAPI 計画

最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

### 要望原文

> Web、JPO確認、個人資料、過去判断を統合するオーケストレーターAPIを実装する。

### ゴール

選択されたfakeソースのEvidenceを、所有者スコープを保って一つのresearch runへ統合する。

### 成功指標

- ソース選択、部分成功、タイムアウト、再試行、上限、引用locatorをAPIテストで観測できる。
- 他所有者のrun取得は404となる。

## ユーザーストーリーと受け入れ条件

### US-01 横断調査を開始する

As a アイデアを検討するユーザー, I want 選択した調査ソースをまとめて実行したい, so that 根拠を一画面で確認できる。

Given: ownerと一つ以上のsourceがある

When: research runを作成する

Then: 成功Evidence、source別状態、locatorが返る

### US-02 失敗したソースを再試行する

As a 調査結果を読むユーザー, I want 失敗したsourceだけを再試行したい, so that 取得済み根拠を失わない。

Given: timeoutまたは日次上限で失敗したsourceがある

When: retryを実行する

Then: 成功済みEvidenceを保持し、再試行したsourceの新しい状態を返す

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
|---|---|---|---|
| Q-01 | 実Supabase認証からownerをどう受け渡すか | CEO | release-gate #31前 |
| Q-02 | 実Web検索の送信同意UIをどう設計するか | CEO | 外部接続PR前 |

## スコープ外

- 実ネットワーク、APIキー、UI、Supabase migration、実認証の設定。
- 外部接続を恒久的に除外すること。release-gate #31で接続を検証する。

## タスク

| ID | 成果物 | 完了判定 | 不確実性 |
|---|---|---|---|
| T-16-1 | local/fakeのrun APIと所有者チェック | 検査: `uv run pytest backend/tests/test_research_orchestrator.py` | 類推可能 |
| T-16-2 | 部分成功、timeout、上限、retryの契約テスト | 検査: 同テストの全ケースが通る | 類推可能 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
|---|---|---|---|
| 所有者境界 | local APIでは`X-Owner-Id`をfake principalとして使う | リクエスト本文のowner指定。偽装を招くため却下 | 実認証導入時に認証principalへ置換 |
| 失敗の扱い | 成功Evidenceを残しsource別状態を返す | 一件の失敗でrun全体を破棄。根拠を隠すため却下 | `partial`とretry APIを契約化 |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
|---|---|---|---|
| 2026-08-09 | 初版 | Issue #16の計画確定 | T-16-1, T-16-2 |
