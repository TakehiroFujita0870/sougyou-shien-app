# Founder Graph UI surface 計画

最終検証日: 2026-09-22

## 要望 / ゴール / 成功指標

### 要望

既存のHome / Project / Knowledge UIを壊さず、Founder GraphのIdeas、Assets、Sources、Peopleを一覧・詳細表示できるUI契約を用意する。

### ゴール

DotsのローカルGraph read surfaceを、ネットワークや外部AIに依存しない、owner-scopedで読み取り専用のReactコンポーネントとして検証できる状態にする。

### 成功指標

- Ideas、Assets、Sources、Peopleの4カテゴリをキーボードで切り替えられる。
- 選択したノードのtitle、kind、snippet、status、relation pathを表示できる。
- empty、loading、unavailable、errorの各状態が明示される。
- private fieldsやlocal-only raw contentをUI fixtureへ渡さない境界をテストで確認する。
- 既存のHome / Project / Knowledgeの順序と挙動を維持したまま、Graphを4番目のWorkspace navigation項目として開ける。

## ユーザーストーリーと受け入れ条件

### US-UI-1 Founder Graph一覧

As a local founder, I want to switch between graph categories, so that I can scan ideas, assets, sources, and people in one surface.

Given: read-only graph results contain nodes from the four categories.

When: the user selects a category tab or presses ArrowRight / ArrowLeft on the tablist.

Then: the active category is announced and only safe result cards for that category are shown.

### US-UI-2 ノード詳細

As a local founder, I want to open a graph result, so that I can inspect its safe fields and relation path.

Given: a result card has a canonical id and safe fields.

When: the user activates the card.

Then: the detail region shows the title, status, safe fields, and relation path without rendering private raw fields.

### US-UI-3 unavailable / empty

As a local founder, I want clear unavailable and empty states, so that I know whether Dots is stopped or the graph has no matching nodes.

Given: the surface is loading, unavailable, failed, or has zero results.

When: the state is rendered.

Then: the region exposes a distinct accessible status message and does not show stale result data.

### US-UI-4 Workspace navigation integration

As a local founder, I want to open Founder Graph from the existing workspace shell, so that the graph is reachable without introducing a second application shell.

Given: the existing workspace navigation exposes Home, Project, and Knowledge.

When: the user selects the Graph item (or uses Alt + Shift + 4).

Then: Graph is shown as the fourth item after Knowledge, the read-only FounderGraphSurface is mounted with safe result/state props, and the legacy three destinations retain their order and behavior.

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| Q-UI-01 | Founder Graphを既存Workspace navigationへ統合する位置 | 利用者兼製品責任者 | 決定済み |

### Q-UI-01 決定

Founder Graphは、既存のHome / Project / Knowledgeを変更・置換せず、Knowledgeの右隣に4番目の「Graph」として追加する。Graphの初期surfaceは読み取り専用とし、結果と状態はAppの明示的なpropsから受け取る。Graph navigationの選択では、Dots内のDBや外部AIへ自動接続せず、空のready stateを安全な既定値とする。

## スコープ外

- shared styleの変更、既存Home / Project / Knowledgeの削除、既存3画面の履歴・archive契約の変更。
- FastAPI、MCP transport、Neo4j、外部AI、実データ接続。
- write操作、物理削除、drag-and-drop graph editor、canvas visualization。
- mobile専用レイアウトの追加。既存レスポンシブprimitiveを利用する。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| UI-1 | `FounderGraphSurface.jsx`のread-only view、tablist、detail、state contract | 検査: `npm.cmd test -- --run src/components/FounderGraphSurface.test.jsx` がgreen | 類推可能 |
| UI-2 | safe fixture adapterとa11y / keyboard regression | 検査: UI-1のテストでprivate field非表示、state、Arrow操作、detailを確認する | 既知 |
| UI-3 | 既存Workspace navigationへのGraph統合 | 検査: App / shell / UX契約テストで4番目のGraph、Alt + Shift + 4、legacy 3画面の維持を確認する | 既知 |
| UI-4 | plan / component self-review | 検査: `npm.cmd run build`、`git diff --check`、既存frontend suite | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| ADR-UI-1 navigation位置 | Founder GraphをKnowledgeの右隣に4番目のread-only workspaceとして追加し、既存3画面の順序・履歴を維持する | 既存Knowledgeの置換、別アプリシェル、Homeへの埋め込みは既存導線と責務を混ぜるため却下 | Graphを既存shellから発見・起動できる |
| ADR-UI-2 safe fields | MCP readのsafe projectionと同じfield名だけを表示し、unknown/private keyを描画しない | dataclass全fieldをspreadする案はprivate leakageを招くため却下 | UIはread-only projectionを入力境界とする |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-09-22 | 初版。既存UIから独立したFounder Graph read surfaceの契約を追加 | T-FG-24を安全なcomponent sliceへ分解するため | UI-1〜UI-3 |
| 2026-09-22 | Q-UI-01を決定。GraphをKnowledgeの右隣に追加し、App / WorkspaceShellへ統合する方針に更新 | Founder Graphを実利用可能な導線から開けるようにするため | UI-3〜UI-4 |
