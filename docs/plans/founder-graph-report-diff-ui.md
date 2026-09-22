# Founder Graph Report Diff UI 計画

最終検証日: 2026-09-22

## G: Goal（ゴール）

T-FG-25の最小UI契約として、二つの安全な`ReportVersion`投影を比較し、固定された8章の追加・変更・変更なしをFounder Graph内で読み取り専用に確認できるようにする。

利用者は、前版と現版の本文の差分だけでなく、引用と撤回された主張を履歴メタデータとして保持したまま確認できる。既存のApp、WorkspaceShell、共有スタイル、DB/API接続には変更を加えず、後続のcomposition sliceから明示的に利用できる独立コンポーネントを成果物とする。

## W: Work（作業範囲）

### 入力契約

- `FounderGraphReportDiff`は`previousReport`と`currentReport`を受け取る。互換の短縮名として`before`と`after`も受け付ける。
- 入力は外部へ送信済みのsafe projectionを想定し、UI側でも章本文、事実、AI推論、未確認、本人判断、claim/evidence ID、引用、撤回された主張だけを静的に再投影する。
- 章名は入力値を信用せず、次の8章をコンポーネントの定数から描画する。

| 章 | 名称 |
| --- | --- |
| 0 | エグゼクティブサマリー |
| 1 | ビジネスモデル |
| 2 | 顧客とマーケットサイズ |
| 3 | 収益モデル |
| 4 | 競争優位性 |
| 5 | 実現可能性 |
| 6 | リスク・撤退ライン |
| 7 | リスクミニマムなロードマップ |

### 表示契約

- 8章を`role=tablist`として表示し、`ArrowRight` / `ArrowLeft` / `Home` / `End`で移動できる。
- 各章へ`追加`、`変更`、`変更なし`を表示する。片方にだけ章本文がある場合は`削除`も表示し、欠落を変更なしと誤認させない。
- 前版・現版の本文と安全な構造化項目を左右に表示する。
- レポートレベルおよび選択章の`引用`、`Claim`、`Evidence`、`撤回された主張`を、編集操作なしの表示専用メタデータとして表示する。
- `loading`、`unavailable`、`error`、`empty`では章本文を表示せず、利用者が次に取るべき状態を`status`または`alert`で通知する。
- `ready`でReportVersionが1件以上ある場合だけ、JSON / Markdownのsafe export intentを表示する。クリックはファイル保存・通信・writeを行わず、safeな形式名とReportVersion IDだけを`onExportRequest`へ渡す。
- `loading`、`unavailable`、`error`、`empty`ではexport intentを発行せず、export操作を表示しない。

### T: Test（検査）

- `src/components/FounderGraphReportDiff.test.jsx`
  - 固定8章の名称と追加・変更・変更なしの分類。
  - tablist、tabpanel、ArrowRightのキーボード操作とARIA契約。
  - 引用・撤回された主張の表示専用保持、およびprivate/rawフィールド非表示。
  - loading / unavailable / error / emptyで古い章を描画しないこと。
- 実行コマンド: `npm.cmd test -- --run src/components/FounderGraphReportDiff.test.jsx`
- 後続の統合時に、既存frontend全体、build、Storybookを実行する。

## スコープ外（Scope-out）

- App.jsx、WorkspaceShell.jsx、共有CSS / design token、ナビゲーションへの配線。
- ReportVersionの保存、編集、削除、永続化、MCP / FastAPI / Neo4j接続。
- 実テキストdiff、inline diff、markdownレンダリング、エクスポート、印刷、PDF。
- Deep Research、Campaign / Run比較、通知、承認、外部送信。
- 追加された主張の真偽判定、撤回操作、引用リンクの外部遷移。

## 受け入れ条件

### US-RD-01 8章の差分確認

Given: 同じownerの前版と現版のsafe ReportVersionがある。

When: 利用者がReport Diffを開く。

Then: 固定8章を確認でき、各章に追加・変更・変更なし（または欠落時の削除）が表示され、タブ操作で章の前版・現版を切り替えられる。

### US-RD-02 provenanceの保持

Given: レポートに引用、claim/evidence ID、撤回された主張が含まれる。

When: 利用者が差分を確認する。

Then: それらは表示専用メタデータとして失われずに見えるが、編集・削除・外部遷移の操作は提供されない。

### US-RD-03 安全な失敗表示

Given: 差分の取得がloading、unavailable、error、emptyのいずれかである。

When: コンポーネントが描画される。

Then: 状態を明示し、古い章や前回の本文を成功結果として表示しない。

### US-RD-04 safe export intent

Given: ready状態で、少なくとも1件のsafe ReportVersion投影がある。

When: 利用者がJSONまたはMarkdownのexportを選択する。

Then: 実ファイルや外部通信を発生させず、形式名、scope、projection、ReportVersion IDだけを`onExportRequest`へ渡し、private/raw fieldsをintentへ含めない。

## ADR

| 判断 | 選択と理由 | 却下案と理由 |
| --- | --- | --- |
| ADR-RD-01 章の正本 | `FOUNDER_GRAPH_REPORT_CHAPTERS`の固定8章をUIの表示正本にする。ReportVersion側のタイトル改変で章契約を壊さないため | 入力の自由なtitleを描画する案は、事業評価レポートの固定章名と表示がずれるため却下 |
| ADR-RD-02 差分単位 | 章単位の状態を`added / changed / unchanged / removed`で示し、本文は前版・現版の左右表示にする | 文字単位のinline diffは保存shapeと編集責務を混ぜ、T-FG-25の初期UIを過大化するため却下 |
| ADR-RD-03 provenance表示 | 引用と撤回された主張をallowlistした文字列メタデータとして表示し、編集操作を持たせない | UIからclaimを直接訂正・削除する案は、ReportVersion write境界と承認・監査を先取りするため却下 |
| ADR-RD-04 composition | 独立componentとして提供し、App / WorkspaceShellへの接続を後続sliceに分離する | 既存shellと同時に変更する案は、所有権とレビュー範囲を広げるため却下 |
| ADR-RD-05 export intent | `onExportRequest`には`format`、`scope`、`projection`、allowlist済み`reportIds`だけを渡し、UIはread-onlyの意図通知に留める | UIからJSON/Markdownを直接生成・downloadする案は、exportのowner/read境界と実ストレージ責務を先取りするため却下 |

## 実装メモ

- 計画タスク: T-FG-25 / US-RD-01〜03
- 成果物: `src/components/FounderGraphReportDiff.jsx`、`src/components/FounderGraphReportDiff.test.jsx`
- safe projection: `projectFounderGraphReportVersion`が、章本文と明示的なprovenanceメタデータだけを新しい表示モデルへコピーする。`private_notes`、`source_text`など未知キーは描画しない。
- 差分契約: `diffFounderGraphReports`が固定8章を返し、片方の章が欠落した場合は`added`または`removed`、同一内容は`unchanged`、それ以外は`changed`とする。
- エラー分類: loading / unavailable / errorは読み取り回復可能状態。入力不足はemptyとして扱い、export intentを含め書き込みや外部副作用は発生しない。
- API互換性: 新規React componentのみ。既存App、API、MCP、DBの変更なし。
- 外部通信: なし。
- 検査結果: focused frontend test `8 tests passed`。
- ループ周回数: 1。初回テストでの期待値調整後、componentとテストを再実行してgreen。

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-09-22 | Report DiffのG/W/T、8章、provenance表示、失敗状態、scope-outを定義 | T-FG-25を独立した読み取りUI sliceへ分解するため | T-FG-25 |
| 2026-09-22 | 独立componentとfocused testを実装 | 既存shellを変更せず、後続compositionで利用できる契約を検証するため | T-FG-25 |
| 2026-09-22 | FounderGraphSurfaceにsafeな`reports`入力による任意のReportsタブを追加 | 独立ReportDiffを既存のFounder Graph面へ段階的にcompositionし、未指定時の4カテゴリ挙動を維持するため | T-FG-25 |
| 2026-09-22 | ready ReportVersionからsafe export intentだけを通知するread-only操作を追加 | export UIの責務を実ファイル生成・通信から分離し、後続のsafe export adapterへ接続可能にするため | T-FG-25 / T-FG-26 |

## composition実装メモ

- `FounderGraphSurface`は`reports={{ previousReport, currentReport }}`を受け取った場合だけReportsタブを追加する。`before` / `after`、`previous` / `current`、2要素配列も読み取り専用の互換入力として扱う。
- レポート版がない場合はReportsタブを追加せず、既存のIdeas / Assets / Sources / Peopleの4カテゴリと状態表示を維持する。
- Reportsタブ内では既存の`FounderGraphReportDiff`をそのまま表示し、レポートの`loading` / `unavailable` / `error` / `empty`状態はReportDiff側の通知契約に委譲する。
- 対象: `src/components/FounderGraphSurface.jsx`、`src/components/FounderGraphSurface.test.jsx`。App、WorkspaceShell、共有スタイル、backend/API/DBは変更しない。
- 検査結果: `npm.cmd test -- --run src/components/FounderGraphSurface.test.jsx src/components/FounderGraphReportDiff.test.jsx` → 17 tests passed。
- export intent: `onExportRequest`は`format`（`json` / `markdown`）、`scope`（`report_versions`）、`projection`（`shareable`）、allowlist済み`reportIds`のみを受け取る。private/raw fields、report object、ファイルAPI、通信APIは渡さない。
- export状態: Reportが`loading` / `unavailable` / `error` / `empty`のときはintentを発行せず、操作を表示しない。
- 検査結果: export intent回帰を含むfocused frontend testは実装後に更新する。
