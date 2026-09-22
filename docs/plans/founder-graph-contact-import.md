# Founder Graph contact import 計画
最終検証日: 2026-09-22

## 要望 / ゴール / 成功指標

### 要望

名刺や手元のCSVから人物・所属組織を、外部通信や推測を行わず、既存の`capture_person` / `capture_organization` write toolへ渡せる入力へ正規化する。

### ゴール

owner境界、入力サイズ、文字列、連絡先、private notesを検証した不変なcapture payloadを作り、人物と組織を別々に保存できる状態にする。取り込み時に関係を自動作成しない。

### 成功指標

- Mappingの行とUTF-8文字列のCSVを同じ正規化契約で処理できる。
- 各人物payloadが`local_only`を保持し、連絡先とprivate notesをshareableへ昇格できない。
- owner_idが期待値と異なる行、未知フィールド、サイズ超過、path traversal、CSV構文エラーを保存前に拒否する。
- 出力は既存8-toolの引数として直接利用でき、人物・組織間の関係を生成しない。

## ユーザーストーリーと受け入れ条件

### US-IMPORT-1 名刺行を正規化する

As a local founder, I want to normalize a bounded contact row, so that I can pass it to the existing write surface without losing the local-owner boundary.

Given: a row has an expected owner_id, a non-empty name, and optional company/contact/private_notes.
When: the row is normalized.
Then: one local-only person capture payload and, when company is present, one local-only organization capture payload are returned with deterministic idempotency keys.

### US-IMPORT-2 CSVを安全に取り込む

As a local founder, I want to import a small CSV without file access or network calls, so that a malformed or oversized export cannot enter the graph.

Given: CSV text uses the supported headers and is within row, byte, and field limits.
When: the CSV is normalized.
Then: each valid row becomes a typed contact record, and no relationships or external calls are produced.

### US-IMPORT-3 不正入力を拒否する

As a local founder, I want invalid rows to fail before persistence, so that private data and cross-owner records cannot be silently misclassified.

Given: a row contains an unknown key, path traversal, an oversized value, malformed CSV, or a different owner_id.
When: normalization is attempted.
Then: a ContactImportError is raised and no capture payload is returned for that input.

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| Q-IMPORT-01 | 画像OCR、名刺アプリ同期、追加CSV列を初期対応するか | 利用者兼製品責任者 | 次のcontact import slice着手前 |

## スコープ外

- 名刺画像OCR、画像/PDFの読み込み、外部連絡先アプリ同期。
- 外部検索、LLMによる名寄せ、重複merge、所属推定、関係の自動作成。
- MCP/API/Appの新規接続、DBへの直接書き込み、ファイルパスの読み取り。
- 実際の`capture_person` / `capture_organization`呼び出しとトランザクション処理。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| IMPORT-1 | `founder_graph_contact_import.py`の型付きpayloadと行正規化 | 検査: Mapping、owner境界、contact/private_notes、組織payload、冪等キー、関係なしをfocused pytestで確認する | 既知 |
| IMPORT-2 | CSV parserと拒否境界 | 検査: malformed CSV、未知列、path traversal、field/row/byte上限、`py_compile`、`git diff --check`を確認する | 類推可能 |
| IMPORT-3 | 本計画と実装メモ | 検査: 受入条件・スコープ外・ADR・検査結果が同じ文書にあることを確認する | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| ADR-IMPORT-1 write surfaceへの変換 | `owner_id`を保持した不変payloadに`to_tool_arguments()`を持たせ、既存8-toolへ委譲する | normalizerが直接DB/MCPを呼ぶ案は責務とテスト境界を広げるため却下 | 入力検証と保存を分離できる |
| ADR-IMPORT-2 local-only default | 人物payloadは常に`local_only`、組織も初期値を`local_only`とする | 名刺の連絡先をshareableへ推測昇格する案は外部送信境界を壊すため却下 | contact/private_notesは外部投影に出ない |
| ADR-IMPORT-3 deterministic identity | 明示idempotency_keyを受け付け、未指定時はownerと正規化内容からSHA-256キーを導出する | 行番号だけをキーにする案は並べ替えで再取り込みできないため却下 | 再送時に既存write surfaceのreplayを利用できる |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-09-22 | 初版。bounded row/CSVから人物・組織capture payloadを作る契約を定義 | T-FG-11の名刺/CSV入力を、OCRや自動関係作成なしで先行検証するため | IMPORT-1〜IMPORT-3 |
| 2026-09-22 | Mapping/CSV normalizerと拒否境界を実装 | 既存write surfaceへ安全に委譲できる純粋なcontact intake sliceを追加するため | IMPORT-1〜IMPORT-3 |

## 実装メモ

- 計画タスク: IMPORT-1〜IMPORT-3
- 受け入れ条件: US-IMPORT-1〜US-IMPORT-3
- 実装: `backend/dots/founder_graph_contact_import.py`に`PersonCapturePayload`、`OrganizationCapturePayload`、`ContactCaptureRecord`、Mapping/CSV/input dispatcherを追加した。
- 入力は最大500行、CSV 1 MiB、1フィールド4,096文字、連絡先16項目に制限し、unknown field、owner mismatch、path traversal、CSV構文/行幅不整合を保存前に拒否する。
- Personの`contact` / `private_notes`は`local_only`固定。Organizationも初期payloadは`local_only`。人物と組織は別payloadで返し、`relationships`は空tupleとして関係を自動作成しない。
- 入力はファイルパスとして扱わず、外部通信・OCR・LLM・名寄せ・DB/MCP呼び出しを行わない。既存8-toolの`to_tool_arguments()`へ変換できる。
- 追加テスト: `backend/tests/test_founder_graph_contact_import.py`（Mapping/CSV成功、write surface互換、冪等キー、private境界、unknown/path/size/owner/malformed拒否）11件。
- エラー分類: 回復可能な入力エラーは`ContactImportError`で拒否し、秘密情報や入力値をログ出力しない。
- API互換性: 既存MCP/API/App変更なし。
- ループ周回数: 1
- 検査結果: `uv run --isolated --python 3.14 pytest backend/tests/test_founder_graph_contact_import.py -q` は11 passed。`py_compile`、全backend pytest、`git diff --check`は親タスクの統合検査で実行する。
