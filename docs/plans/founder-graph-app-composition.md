# Founder Graph App composition 計画

最終検証日: 2026-09-22

## 要望 / ゴール / 成功指標

要望: 既存の安全なFounder Graph read projectionと任意の事業評価ReportVersionを、アプリのGraph surfaceへ接続する。

ゴール: `App`がGraphの結果、状態、レポート差分入力を明示的なpropsとして受け取り、外部通信や新しいwrite責務を持たずに`FounderGraphSurface`へ伝播する。

成功指標: ReportVersionを渡したときだけGraphにReportsカテゴリが現れ、propsを省略した既存呼び出しでは4カテゴリの読み取り専用surfaceが維持される。

## ユーザーストーリーと受け入れ条件

### US-AC-01 report propagation

As a ChatGPT / read composition layer, I want optional report versions to reach the Graph surface, so that report diff UI can render data already fetched by a safe upstream adapter.

Given: `founderGraphReports`に前版・現版のreport projectionが渡される。

When: 利用者がAppのGraphへ移動する。

Then: Reportsカテゴリが表示され、選択時に既存のread-only report diff surfaceが表示される。

### US-AC-02 backward-compatible empty default

As an existing App caller, I want to omit report props, so that the current Graph behavior remains unchanged.

Given: `founderGraphReports`が省略される。

When: 利用者がAppのGraphへ移動する。

Then: Reportsカテゴリもreport diffも表示されず、Ideas / Assets / Sources / Peopleの4カテゴリだけが表示される。

## スコープ外

- GraphReadPort、Neo4j、MCP、FastAPI、外部通信、Deep Research、write-backの追加。
- reportの取得・保存・変換・認可。
- shared styles、ナビゲーション構造、既存のFounderGraphSurfaceのprojection境界の変更。

## タスク

| ID | 成果物 | 完了判定（検査） | 不確実性 |
| --- | --- | --- | --- |
| T-AC-01 | `App`のoptional `founderGraphReports` propとSurface伝播 | App Graph composition test | 既知 |
| T-AC-02 | reportsあり / 省略時の回帰テスト | `src/App.founder-graph.test.jsx` focused test | 既知 |
| T-AC-03 | 実装メモと検査結果 | frontend test、build、diff check | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| ADR-AC-01 report input | `App`は`founderGraphReports`を受け取り、既存の`FounderGraphSurface`へそのまま渡す。正規化・allowlistはSurface側の既存境界に委譲する | Appでreportを再構成する方式は、composition層へdomain知識とprivate-fieldリスクを持ち込むため却下 | upstreamのsafe projectionと既存UI契約を再利用できる |
| ADR-AC-02 default | 省略時は`null`として渡し、Surfaceの既存4カテゴリdefaultを維持する | Appで空report配列を生成する方式は、任意入力の存在としてReportsカテゴリを誤表示しうるため却下 | 既存呼び出しとSSRの互換性を保つ |

## 実装メモ

- 計画タスク: T-AC-01〜03
- 受け入れ条件: US-AC-01〜02
- 成果物: `src/App.jsx`、`src/App.founder-graph.test.jsx`
- composition: `founderGraphReports = null`を受け、Graph routeで`FounderGraphSurface reports={founderGraphReports}`へ伝播する。
- エラー分類: 新規エラー経路なし。既存のGraph surfaceがloading / unavailable / errorを表示する。
- API互換性: 既存propsは変更なし。新規propはoptional。
- 外部通信: なし。
- 検査結果: `npm.cmd test -- --run src/App.founder-graph.test.jsx` → 2 passed。`npm.cmd test -- --run` → 44 files / 302 tests passed。`npm.cmd run build` → PASS。`npm.cmd run build-storybook` → PASS。`git diff --check` → PASS。
- ループ周回数: 1。

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-09-22 | App compositionのG/W/T、optional reports入力、4カテゴリdefaultを定義 | Reports UIを既存のread-only Graphへ接続するため | T-AC-01〜03 |
| 2026-09-22 | `App`にoptional `founderGraphReports`を追加し、Graph surfaceへ伝播するfocused testを実装 | App境界でreport diff入力の有無を固定するため | T-AC-01〜03 |
