# Founder Graph Report Impact / Diff 計画

最終検証日: 2026-09-22

## 要望 / ゴール / 成功指標

### 要望

追加質問または追加Evidenceを受けたReportVersionについて、固定8章のどの章が影響を受けたかを純粋なバックエンド契約として算出する。前版は読み取り専用で保持し、現版に含まれる引用・Evidence参照・撤回された主張を表示用メタデータとして残す。

### ゴール

safeなReportVersionまたはsection mappingから、章名、前版・現版の内容、差分状態、影響章、変更なし章、provenanceメタデータを決定的かつ外部通信なしに得られるようにする。

### 成功指標

固定8章を同じ順序で返し、内容・構造化項目・参照メタデータの変更を`added` / `changed` / `unchanged` / `removed`へ分類する。private/raw fieldは出力へ含めず、入力mappingを変更しない。GraphWrite、MCP、API、UI、外部サービスへ変更を加えない。

## ユーザーストーリーと受け入れ条件

### US-RD-01 追加質問の影響章を特定する

As a 単独Founder, I want 前版と追調査後のReportVersionを章単位で比較したい, so that 追加質問で再検討する章だけを把握できる。

Given: 同一ownerの前版と現版のsafe ReportVersion mappingがあり、現版では一部章の本文または構造化項目が変わっている。

When: `diff_report_versions`を呼び出す。

Then: 固定8章の各状態と、`impacted_chapter_ids` / `unchanged_chapter_ids`が決定的に返る。

### US-RD-02 前版とprovenanceを保持する

As a Report reader, I want 前版を変更せず引用と撤回された主張を確認したい, so that 改訂理由と根拠の履歴を追跡できる。

Given: 前版・現版にreport/section単位のreferences、evidence IDs、withdrawn claimsがある。

When: 差分契約を生成する。

Then: 前版・現版のsafe projectionとメタデータが不変値として返り、旧mappingの値と構造は変更されない。

### US-RD-03 private/raw fieldを閉じる

As a local owner, I want private/raw fieldが差分結果へ流出しないようにしたい, so that report diffを後続の表示・調査入力へ渡しても非公開原文を含まない。

Given: 入力mappingに`private_notes`、`source_text`、`raw`または未知のfieldが含まれている。

When: safe projectionを生成する。

Then: 明示allowlist外の値は結果へ含まれず、許可された文字列メタデータだけが返る。

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| Q-RD-01 | 章の影響判定をLLM分類へ委譲するか | なし。初期sliceは本文・構造化項目・参照の決定的比較とする | 2026-09-22 |

## スコープ外

- ReportVersionの保存、改訂生成、旧版の削除、GraphWrite、Neo4j migration。
- MCP、FastAPI、ChatGPT Deep Research、外部通信、通知、承認。
- UI、React component、inline text diff、Markdown/PDF export。
- Evidenceの真偽判定、withdrawn claimの撤回操作、LLMによる章分類。
- `docs/inherited/` の変更。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| RD-1 | immutable safe projectionと固定8章のbackend contract | 検査: `test_project_report_version_accepts_domain_and_safe_mappings`、`test_projection_omits_private_and_raw_fields`、`test_projection_does_not_mutate_input` がgreen | 類推可能 |
| RD-2 | 章差分・impact集計とprovenance metadata | 検査: `test_diff_marks_added_changed_unchanged_and_removed`、`test_diff_includes_references_and_withdrawn_claims` がgreen | 類推可能 |
| RD-3 | module self-reviewと静的検査 | 検査: `uv run --isolated --python 3.14 pytest backend/tests/test_founder_graph_report_diff.py -q`、`uv run --isolated --python 3.14 python -X utf8 -m py_compile backend/dots/founder_graph_report_diff.py`、`git diff --check` | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| ADR-RD-01 差分単位 | 章単位の`added` / `changed` / `unchanged` / `removed`を返す。初期の影響分析に必要な情報を保ち、文字単位diffを後続へ分離できるため | inline diffは表示責務と本文の保存shapeを結合し、今回のpure contractを広げるため却下 | `impacted_chapter_ids`はadded/changed/removed、`unchanged_chapter_ids`はunchangedとなる |
| ADR-RD-02 章名の正本 | `REPORT_SECTION_TITLES`の固定8章をbackend出力へ使う。mappingのtitle改変で事業評価章立てが変わらないため | 入力mappingの自由なtitleを採用する案はReportVersion契約と表示がずれるため却下 | 入力titleは無視し、idと固定titleだけを返す |
| ADR-RD-03 安全境界 | 明示allowlistの本文・分類・ID・参照メタデータだけを新しいimmutable projectionへコピーし、private/raw/未知fieldは破棄する | mapping全体をdeep copyする案は将来fieldの漏出経路になるため却下 | projectionと差分結果にprivate/raw fieldは存在しない |
| ADR-RD-04 旧版保持 | 前版と現版を別々の凍結projectionとして返し、入力mappingへ書き戻さない | 現版を前版へ上書きする案は複数試行の比較と監査を壊すため却下 | 改訂生成やGraphWriteは後続sliceへ分離する |

## 実装メモ

- 計画タスク: RD-1〜RD-3 / US-RD-01〜03
- 成果物: `backend/dots/founder_graph_report_diff.py`、`backend/tests/test_founder_graph_report_diff.py`
- API互換性: 新規pure moduleのみ。既存API、MCP、GraphWrite、Neo4jには影響なし。
- エラー分類: 不正な章IDや非mappingのsection collectionは回復可能な入力エラーとして`ReportDiffInputError`へ分類する。未知/private fieldは投影から除外する。
- 外部通信: なし。
- 追加テスト: `backend/tests/test_founder_graph_report_diff.py` の6テスト。
- 検査結果: focused pytest `6 passed`、`uv run --isolated --python 3.14 python -X utf8 -m py_compile backend/dots/founder_graph_report_diff.py` 成功、`git diff --check` 成功。
- ループ周回数: 1。

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-09-22 | T-FG-19をpure backend impact/diff sliceとして定義 | 追加質問後に再評価する章と旧版保持の契約を、UIや保存処理から分離するため | RD-1〜RD-3 |
| 2026-09-22 | immutable projection、固定8章の差分、impact集計、provenanceメタデータを実装 | 旧版を変更せず、追加質問とEvidenceの改訂境界を決定的に検証するため | RD-1〜RD-3 |
