# space共通知識境界 計画
最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標
1つの資料原本をuser spaceへ一度だけ保存し、会話・project・調査・ideaからreference metadataで再利用するlocal/fake契約を作る。owner外の原本・派生物・参照が検索結果に出ないことを契約テストで確認する。

## ユーザーストーリーと受け入れ条件
### US-1 原本を一度だけ保存する
As a 利用者, I want 同じ資料を重複保存せず再利用したい, so that spaceの原本を一元管理できる。
Given: 同じownerが同じcontent hashの資料を複数経路から登録する
When: space repositoryへ保存する
Then: 1つのoriginal_idと既存originalを返し、派生物は1組だけ保持する。

### US-2 referenceを関連付ける
As a 利用者, I want conversation/project/research/ideaから資料を参照したい, so that文脈だけを再利用できる。
Given: ownerが有効なoriginalを持つ
When: source kind、source id、locatorを指定してreferenceを作る
Then: originalを複製せずmetadataだけが保存され、owner外の参照は拒否される。

### US-3 削除を伝播する
As a 利用者, I want原本削除で派生物と参照も無効化したい, so that削除済み本文が検索へ戻らない。
Given: originalにextracted text、embedding、引用locator、referenceがある
When: ownerがoriginalを削除する
Then: original、派生物、reference、横断検索結果が不可視になり、既存参照はunavailableになる。

## スコープ外
- Supabase実接続、外部AI・embedding provider、外部保存、個人情報送信。
- App.jsxやUI、実ファイル抽出器、匿名化器、認証実装。

## タスク
| ID | 成果物 | 完了判定（検査:） | 不確実性 |
|---|---|---|---|
| T-SPACE-01 | local/fake SpaceKnowledgeRepository | 検査: owner、hash重複、reference、削除伝播、横断検索の契約pytest | 類推可能 |

## ADR
| 判断 | 選択と理由 | 却下案と理由 | 結果 |
|---|---|---|---|
| ADR-SPACE-01 | 原本・派生物・referenceを分離する。原本1件を複数文脈から安全に参照できる | 文脈ごとに原本を複製する案は重複・削除漏れを生むため却下 | local repositoryで一意hashと削除伝播を検証する |
| ADR-SPACE-02 | ownerをrepository引数から確定し、requestのowner値を受け取らない | request owner_idを信頼する案は他owner参照を許すため却下 | 全read/write/searchでowner一致を要求する |
| ADR-SPACE-03 | 既存の`file_ingestion`の抽出・削除語彙とresearch schemaのowner境界を参照し、依存追加なしの小さなfake repositoryを置く | 新規ORM・UI基盤・永続化adapterはbundle、security、license、更新責任を増やし、既存契約と重複するため却下 | 2箇所以上で同じspace操作が必要になった時、Supabase adapterへ移行してfakeを削除する |

## 変更履歴
| 日時 | 変更 | 理由 | 影響タスク |
|---|---|---|---|
| 2026-08-09 | 初版 | 共通知識の原本一元化と削除境界を定義 | T-SPACE-01 |
