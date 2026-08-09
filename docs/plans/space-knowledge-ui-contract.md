# space共通知識 UI契約 計画

最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

PR #92の固定principal境界をUIへ接続し、同一spaceの有効な知識だけを出典とlocator付きで表示する。削除済みreferenceを候補、検索、引用UIに表示しないことを成功指標とする。

## ユーザーストーリーと受け入れ条件

### US-SPACE-UI-1
As a 利用者, I want 資料の参照元と位置を確認する, so that 会話、project、research、ideaで根拠へ戻れる。
Given: 有効なspace referenceがある
When: 資料一覧を開く
Then: source kind、source id、locatorを表示し、ownerの入力欄や切替UIを表示しない

### US-SPACE-UI-2
As a 利用者, I want 削除済み資料を見ない, so that 無効な根拠を判断に使わない。
Given: 原本削除でreferenceがunavailableになった
When: 資料一覧または引用一覧を開く
Then: unavailable referenceとdeleted documentを表示しない

### US-SPACE-UI-3
As a キーボードまたはスクリーンリーダー利用者, I want mobileでも参照情報を読む, so that 同じspace知識へ到達できる。
Given: PCまたは390px viewportである
When: 資料カードを読む
Then: 出典リストは意味を持つリストとして読み上げられ、横overflowを作らない

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| Q-SPACE-UI-1 | conversation/project/research/ideaの詳細画面での引用配置 | UI・UX部 | 各domain PR開始前 |

## スコープ外

- Supabase実接続、外部AI・embedding、外部保存、実個人情報送信
- owner IDのUI入力、requestへのowner ID引き渡し、個別grant
- #92 repositoryの変更、chat/project/research/idea本文の実装

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-SPACE-UI-1 | reference表示とunavailable除外 | 検査: `FileLibrary.test.jsx` | 既知 |
| T-SPACE-UI-2 | PC/mobile Storyとa11y契約 | 検査: Story exportとa11y test | 類推可能 |
| T-SPACE-UI-3 | F5/hydration表示契約 | 検査: 初期document propsのDOMテスト | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| ADR-SPACE-UI-1 | 既存`FileLibrary`のlocal/fake adapterを再利用し、reference metadataだけを表示する | UIからownerを渡すadapterは#92固定principal契約を破るため却下 | owner値をprops/APIへ追加しない |
| ADR-SPACE-UI-2 | Reactの条件レンダーとTailwind utilityを使う | 新しいUI基盤はbundle、security、license、更新責任を増やすため却下 | 依存追加なし |
| ADR-SPACE-UI-3 | metadataが2箇所以上で必要になったときのみ小さな共通componentへ抽出する | 先行した共通化はdomain UIの差を隠すため却下 | 現PRはFileLibrary内に限定 |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | 初版 | #92の固定principal・削除伝播契約をUIへ接続 | T-SPACE-UI-1〜3 |
