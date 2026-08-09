# T-IA-02 / T-IA-07: 3 surface presentation inventory 計画

最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

要望: Home / Project / Knowledgeの3 item nav、compact header、quiet chromeを、runtime配線なしのpresentation契約として記録する。

ゴール: 実装担当が後続のsurface変更を同じ情報階層で検討できるStoryと計画文書を用意する。

成功指標: Empty、Populated、Loading、Error、390px、DesktopのStoryを閲覧でき、first viewportのprimary actionまたはcomposer、3 item nav、context label、quiet local/fake badge、禁止する密度パターンを観測できる。

## ユーザーストーリーと受け入れ条件

### US-1: 3 surface navigation

As a workspace利用者, I want Home / Project / Knowledgeの3項目を静かなnavで見つけたい, so that 作業場所を短い視線移動で判断できる。

Given: Desktopまたは390pxのpresentation Storyを開いている。

When: first viewportのnavを確認する。

Then: Home、Project、Knowledgeの3項目だけが表示され、現在位置は`aria-current="page"`相当の状態で判別できる。

### US-2: primary surface density

As a workspace利用者, I want first viewportでprimary actionまたはcomposerを確認したい, so that 次の行動を探すためにスクロールしなくてよい。

Given: Empty、Populated、Loading、Errorの各Storyを開いている。

When: first viewportを確認する。

Then: 状態に応じたprimary actionまたはcomposerが表示され、巨大heading、重複CTA、空カード、常設開発警告は表示されない。

### US-3: quiet chrome and context

As a workspace利用者, I want compact header、context label、quiet local/fake badgeを区別して読めたい, so that 現在地と実行環境を誤認しない。

Given: PopulatedまたはErrorのpresentation Storyを開いている。

When: headerとsurfaceの補助情報を確認する。

Then: compact breadcrumb、context label、local/fake badgeが過度な装飾なしに表示され、エラー状態は次の行動を示す。

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| なし | runtimeのnav wiringとsurface実装は後続assignmentで扱う | 統合・リリース管理部 | 後続assignment受領時 |

## スコープ外

- `App.jsx`、`WorkspaceShell.jsx`、`src/styles.css`、runtime nav wiringの変更。
- conversation workflow、project workflow、repository、context snapshot allowlistの実装。
- 外部接続、API、認証、永続化、実際のprimary action発火。
- Storyをruntime UIの実装完了証跡として扱うこと。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-IA-02 | 3 item nav、compact breadcrumb/context label、quiet local/fake badgeのinventory | 検査: 本文のUS-1とStoryのContractPreviewに同じ要素がある | 既知 |
| T-IA-07 | Empty、Populated、Loading、Error、390px、Desktopのpresentation Story | 検査: `WorkspaceShell.presentation.stories.jsx`に6つのexportとviewport設定がある | 既知 |
| T-IA-08 | first viewport密度の禁止事項 | 検査: Storyにprimary action/composerがあり、禁止要素のテキストがない | 既知 |
| T-IA-09 | 最終検査 | 検査: `npm run build-storybook`、`git diff --check`、UTF-8 read-backが成功 | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| Storyの責務 | runtimeを変更しないContractPreviewとして状態と密度を可視化する。割当の所有権と契約を守れる。 | `WorkspaceShell.jsx`へ3 item navを直書きする案は、runtime nav wiring禁止に反するため却下。 | Storyを追加する。 |
| 状態表現 | Empty、Populated、Loading、Errorを同じsurface frameで切り替える。状態差分とchrome差分を分離して確認できる。 | 状態ごとに別layoutを作る案は、情報階層の比較を妨げるため却下。 | 1つのpreview componentをStory内に置く。 |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | 初版作成 | #112提供契約をpresentation-onlyのinventoryへ分解 | T-IA-02、T-IA-07、T-IA-08、T-IA-09 |
