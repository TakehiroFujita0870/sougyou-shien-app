# PC・スマホ・キーボード・a11y CI 計画

最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

要望: 主要UXをPC、スマホ、キーボード、スクリーンリーダー想定でCI検証する。

ゴール: 主要App Storyのviewportとa11y違反、キーボード操作、フォーカス表示、タップ領域を自動検証する。

成功指標: PR CIでa11y errorが失敗となり、PC/mobile Storyと観測可能なキーボードテストが実行される。

## ユーザーストーリーと受け入れ条件

### US-1
As a PC利用者, I want キーボードだけでワークスペースを移動する, so that ポインティングデバイスなしで主要画面を操作できる。
Given: Appが表示されている
When: ナビゲーションbuttonをEnterまたはSpaceで操作し、衝突しにくいshortcutを使う
Then: 対応するworkspaceが表示され、入力中のショートカットは無視される

### US-2
As a フォーム利用者, I want Enter、Shift+Enter、Escapeを使い分ける, so that 入力を中断せずに送信または閉じられる。
Given: プロフィールdialogまたは複数行入力欄が表示されている
When: Enter、Shift+Enter、Escapeを入力する
Then: 送信、改行、dialog closeの結果がテストで観測できる

### US-3
As a スマホ利用者, I want 十分なタップ領域を持つ主要UIを見る, so that 小さい画面で操作できる。
Given: App Storyをdesktopとmobile viewportで描画する
When: Storybookのa11y検査を実行する
Then: a11y errorがCIを失敗させ、主要buttonの最小タップ領域をテストする

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| Q-1 | Storybook Vitest addonの現行packageとVitest 3の互換性 | 実装者 | 実装前スパイク完了時 |

## スコープ外

- ビジュアル刷新、対応ブラウザの追加
- 実ユーザーデータ、外部API、認証情報の利用
- 全コンポーネントのE2E化

## スパイク

| ID | 結論・調査方法・時間上限 |
| --- | --- |
| S-1 | `npm view @storybook/addon-vitest peerDependencies`と公式packageの導入結果を15分以内に確認し、非互換なら既存Vitestとaxe-coreの検査へ戻す。 |

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-1 | App desktop/mobile Storyとa11y設定 | 検査: Storybook buildとa11y検査コマンドが成功 | 類推可能 |
| T-2 | キーボード・フォーカス・タップ領域テスト | 検査: `npm run test`で操作結果を確認 | 類推可能 |
| T-3 | CI workflow | 検査: workflowがa11yコマンドを実行 | 既知 |
| T-4 | 依存互換性スパイク記録 | 検査: S-1の結論を変更履歴へ記録 | 未知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| a11y実行 | axe-coreをVitestのDOM testとしてCI実行し、Storybook addonはUIで`test: error`を表示する。現行Vitest 3とStorybook 9を維持できる。 | Storybook Vitest addonのbrowser providerは現行構成と追加互換性調整を要するため、このPRでは却下。Storybook buildだけの検査もCI失敗化できないため却下。 | 採用 |
| shortcut | Alt+Shift+数字をPC用shortcutにする。ブラウザ標準shortcutと衝突しにくく、入力欄では無視できる。 | 数字単独は文字入力と衝突するため却下。 | 採用 |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | 初版作成 | Issue #20をテスト可能な作業へ分解 | T-1, T-2, T-3, T-4 |
| 2026-08-09 | S-1完了 | addon 9.1.20はStorybook 9/Vitest 3対応を確認したがbrowser provider導入が別互換性作業になるためaxe-core CIを採用 | T-1, T-3, T-4 |
