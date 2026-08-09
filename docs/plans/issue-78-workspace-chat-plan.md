# Issue #78 workspace AI chat 計画

最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

要望: workspace内のAIチャットを、space全体を扱うportfolio stewardとproject単位会話を切り替えられるlocal/fake UIとして提供する。

ゴール: 利用者がどのworkspaceページからでもAIチャットへ入り、文脈を確認して会話し、候補を採用・保留・理由付き却下できる。

成功指標: 外部送信なしで、F5相当の再hydrate後も保存済み会話と未送信入力を失わず、PCと390pxで主要操作を完了できる。

## ユーザーストーリーと受け入れ条件

### US-78-01 space会話を始める

As a 利用者, I want sidebarのAIチャットからportfolio stewardとの会話を始める, so that 現在のページとspace内の情報を踏まえて考えられる。

Given: 任意のworkspaceページを表示している
When: AIチャットを選ぶ
Then: 現在ページ、プロフィール、space knowledgeを含む文脈が会話ページに表示される。

### US-78-02 project会話を分ける

As a 利用者, I want project会話をspace会話から分ける, so that 個別案の検討を混ぜない。

Given: portfolio steward会話を表示している
When: project会話を選ぶ
Then: 会話のscopeがprojectとして表示され、space会話のメッセージは表示されない。

### US-78-03 候補を判断する

As a 利用者, I want 提案候補を採用、保留、理由付き却下できる, so that 判断を自分で保留または確定できる。

Given: local replyが候補を提示している
When: 採用、保留、または理由を入力して却下を選ぶ
Then: 採用だけがproject化済みと表示され、保留と却下はprojectを作らない。

### US-78-04 再開する

As a 利用者, I want 会話と未送信入力を再開する, so that hydrateが遅くても書き始めた内容を失わない。

Given: 保存済み会話を非同期で読み込んでいる
When: 読み込み完了前に入力する
Then: 利用者が入力した値を保存済みdraftで上書きしない。

## スコープ外

- 外部AI、ネットワーク送信、Supabase、embedding、実ファイル処理
- owner ID入力、owner切替、個別grant、削除済みreferenceの表示
- entitlementの変更、モデルカタログ変更、Pro機能の実装
- #69のアイデア候補UI、#97の資料library、WorkspaceShellの構造変更

## タスク

| ID | 成果物 | 完了判定 | 不確実性 |
| --- | --- | --- | --- |
| T-78-01 | chat画面とlocal repository | 検査: component testで送信、scope、判断、hydrateを確認 | 既知 |
| T-78-02 | Appのchat placeholder接続 | 検査: App testでナビゲーションと現在ページcontextを確認 | 類推可能 |
| T-78-03 | Storybookとa11y検査 | 検査: storyのDesktop/Mobileとaxe testが通る | 類推可能 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| 会話保存 | 既存React stateとbrowser localStorageだけをadapter化し、F5再開を検証する | 新規状態管理ライブラリは依存、bundle、更新責任を増やすため却下 | 外部送信なし |
| UI | 既存Tailwind utilityとWorkspaceShell navigationを再利用する | 独自dialog/menuやstyled UI基盤は二重基盤になるため却下 | 新規依存なし |
| 文脈 | fixed principalのspace knowledgeを表示用metadataとして受け取る | UIからowner/grantをrepositoryへ渡す案は#92契約に反するため却下 | 同一spaceのみ |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | 初版 | Issue #78とportfolio steward判断を反映 | T-78-01からT-78-03 |
