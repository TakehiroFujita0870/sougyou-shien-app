# 全量エクスポートとアカウント削除のlocal/fake契約 計画
最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標
要望: 本人のプロフィール、アイデア、資料メタデータ、調査、意思決定をJSONとMarkdownでエクスポートし、アカウント削除時に原本、抽出本文、埋め込み、検索索引を除外した完了監査を返すlocal/fake契約を作る。

ゴール: 外部接続なしで、所有者限定のexport、削除manifest、完了監査を決定的に検証できるAPIにする。

成功指標: owner Aのexportと削除結果にowner Bの値がなく、削除後のAの全対象がexcludedとなり、Bのexportが不変であることをAPIテストで観測できる。

## ユーザーストーリーと受け入れ条件
### US-1
As a データ所有者, I want 自分の記録をJSONとMarkdownで取得する, so that 保管または移行に使える。

Given: local/fakeリポジトリに本人の記録がある
When: 認証済み本人がexport APIを呼ぶ
Then: プロフィール、アイデア、資料メタデータ、調査、意思決定を含むJSONとMarkdownが返る

### US-2
As a データ所有者, I want 削除対象を確認して削除する, so that 原本と派生データを検索から除外できる。

Given: 本人の資料と派生データが存在する
When: 認証済み本人が削除APIを呼ぶ
Then: manifestに原本、抽出本文、埋め込み、検索索引が含まれ、完了監査の全対象はexcludedとなる

### US-3
As a 分離された利用者, I want 他人のデータを取得も削除もできない, so that 所有境界が守られる。

Given: owner Aとowner Bの記録が存在する
When: owner Aがexportまたは削除を実行する
Then: 応答にowner BのIDや内容がなく、owner Bのexport結果は変更されない

### US-4
As a 運用担当者, I want 未決の保持境界を知る, so that 実接続前に決裁できる。

Given: local/fake契約の文書を確認する
When: 保持範囲を読む
Then: 法定保存期間とbackup保持方針が未決事項として記載される

## 質問リスト
| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| Q-1 | 法定保存が必要なデータ種別と期間 | CEO・法務 | 実接続の削除設計前 |
| Q-2 | backup内の削除方式と保持期間 | CEO・運用 | 実Supabase接続前 |

## スコープ外
- 実Supabase、オブジェクトストレージ、検索サービス、外部APIへの接続。
- 実ユーザーの個人情報送信、APIキー、課金、外部公開。
- 法定保存期間またはbackup保持方針の決定。
- App.jsxまたは既存の画面変更。

## タスク
| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-1 | export/delete契約の失敗テスト | 検査: `uv run pytest backend/tests/test_account_privacy_api.py` が修正前に失敗する | 既知 |
| T-2 | 決定的local/fakeリポジトリとAPI | 検査: owner分離、manifest、auditのAPIテストが通る | 類推可能 |
| T-3 | 計画と未決保持境界の記録 | 検査: 計画に質問リストとADRがある | 既知 |

## ADR
| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| export形式 | 一つの応答に構造化JSON値とMarkdown値を返す。決定的テストで双方を確認できる。 | ファイル生成は保存先と外部配布を追加するため却下。 | 実接続時にダウンロードストリームへ置換できる。 |
| 非所有データ | exportと削除は認証済みownerでリポジトリを絞る。非所有IDを受け取らない。 | クライアント指定ownerは偽装可能なため却下。 | Bの存在を応答に含めない。 |
| 削除完了 | manifestの全artifactをexcludedとして監査に残す。 | 物理削除済みと主張する実ストレージ操作はlocal/fakeでは検証不能なため却下。 | 実接続で削除ジョブとbackup方針へ対応する。 |

## 変更履歴
| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | 初版作成 | Issue #21をowner分離可能なlocal/fake契約へ分解 | T-1, T-2, T-3 |
