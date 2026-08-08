# ファイル取込スパイク（SP-03）

最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

> PDF、DOCX、TXT、CSVを初回候補として、取込状態・拒否条件・抽出メタデータを決める。画像PDF OCRは初回対象外の前提を検証する。

ゴールは、非信頼ファイルを外部送信せず判定し、抽出物と削除対象を追跡できる最小契約を定めることです。

成功指標は、下表20件の期待判定、ページとハッシュの対応、削除manifestの単体テストが全て通ることです。

## ユーザーストーリーと受け入れ条件

### US-1

As a 資料を登録するユーザー, I want 危険または読めないファイルが明示的に拒否される, so that 検索対象へ混入しない。

Given: PDF、DOCX、TXT、CSVの候補ファイル
When: 形式、サイズ、暗号化、ページ数、破損を検査する
Then: `supported`、`unsupported`、`encrypted`、`oversize`、`malformed` のいずれかが返る

### US-2

As a 資料を登録するユーザー, I want 抽出箇所を原本の版とページへ戻せる, so that 調査根拠を確認できる。

Given: fake extractor がページ本文を返す
When: 結果を正規化する
Then: 各結果に `document_id`、`version`、`page`、`content_hash` がある

### US-3

As a 資料を削除するユーザー, I want 削除対象が追跡される, so that 原本と検索用データが残らない。

Given: 文書版と抽出・断片・埋め込みの識別子
When: 削除manifestを作る
Then: 四種別と `document_id`、`version` を含むmanifestが返る

## 20件の合成fixture評価

上限はスパイク専用の暫定値: 25 MiB、PDF 500ページ、展開後DOCX 100 MiB。実サービスの保存上限は Q-02 のCEO決裁まで未決定です。全fixtureは合成で、実ユーザー資料、外部AI、クラウドへ送信していません。

| ID | 形式 | サイズ | ページ/行 | 文字コード | 条件 | 期待 | 結果 |
| --- | --- | ---: | --- | --- | --- | --- | --- |
| F01 | PDF | 80 KiB | 1 | UTF-8 | 通常テキスト | supported | pass |
| F02 | PDF | 1.2 MiB | 12 | UTF-8 | 日本語本文 | supported | pass |
| F03 | PDF | 3 MiB | 4 | binary | 画像のみ | supported、OCR対象外 | pass |
| F04 | PDF | 2 KiB | 1 | binary | `/Encrypt` | encrypted | pass |
| F05 | PDF | 30 MiB | 2 | binary | 上限超過 | oversize | pass |
| F06 | PDF | 40 KiB | 501 | UTF-8 | 巨大ページ数 | oversize | pass |
| F07 | PDF | 1 KiB | - | binary | 壊れたheader | malformed | pass |
| F08 | DOCX | 70 KiB | 2 | UTF-8 | 通常文書 | supported | pass |
| F09 | DOCX | 90 KiB | 3 | UTF-8 | 日本語本文 | supported | pass |
| F10 | DOCX | 1 KiB | - | binary | 非ZIP | malformed | pass |
| F11 | DOCX | 3 MiB | 8 | UTF-8 | 展開後101 MiB | oversize | pass |
| F12 | DOCX | 150 KiB | 1 | UTF-8 | VBAマクロ | unsupported | pass |
| F13 | DOCX | 120 KiB | 2 | UTF-8 | 埋込スクリプト | unsupported | pass |
| F14 | TXT | 12 KiB | 1 | UTF-8 | 通常文書 | supported | pass |
| F15 | TXT | 8 KiB | 1 | UTF-16LE | BOMあり | supported | pass |
| F16 | TXT | 4 KiB | 1 | Shift_JIS | 判定不能 | malformed | pass |
| F17 | CSV | 60 KiB | 500 | UTF-8 | UTF-8 RFC4180風 | supported | pass |
| F18 | CSV | 40 KiB | 300 | UTF-16LE | BOMあり | supported | pass |
| F19 | CSV | 2 KiB | - | UTF-8 | 不正引用符 | malformed | pass |
| F20 | TXT | 4 KiB | 1 | UTF-8 | プロンプト注入文字列 | supported、非信頼 | pass |

画像のみPDFは形式上受入可能ですが、抽出本文は空になり `needs_ocr` メタデータを付けます。OCRは初回対象外であり検索可能にしません。DOCXのマクロ、埋め込みスクリプト、ZIP爆弾は抽出器を起動する前に拒否します。プロンプト注入文字列は内容を命令として実行せず `untrusted` として扱います。

## 状態・失敗分類

状態は `received -> validating -> extracting -> indexed -> searchable`、拒否は `rejected`、削除は `deleting -> deleted` とします。初回の判定関数は同期・純粋であり、保存、ネットワーク、OCR、埋め込みを行いません。

| 分類 | 原因 | 次の操作 |
| --- | --- | --- |
| unsupported | 拡張子・署名不一致、マクロ、スクリプト | 安全な形式へ変換して再登録 |
| encrypted | 暗号化PDF | パスワードを除去した版を登録 |
| oversize | 原本、ページ数、展開後サイズが上限超過 | 小分けにして再登録 |
| malformed | 署名、文字コード、CSV構文、構造不正 | 元ファイルを修正して再登録 |

## 削除境界

削除manifestは `original`、`extracted_text`、`chunks`、`embeddings` を必須種別として列挙します。実ストレージとDBは本スパイクの対象外のため、manifestの全項目が完了するまで状態を `deleted` に遷移させない設計契約だけを定義します。既存レポートには原典を残さず、将来は参照不能表示とハッシュのみを残すかを Q-06 で決めます。

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| Q-02 | 本番の1ファイル・保存容量・保持期間の上限 | CEO | 原価スパイク後 |
| Q-06 | 削除後レポートにハッシュのみを残すか | CEO | 削除設計PR前 |

## スコープ外

- Supabase migration、実ストレージ、OCR、埋め込みAPI、UI、Web/JPO検索。
- 実ファイルのマルウェアスキャン、パスワード処理、クラウドまたは外部AIへの送信。

## タスク

| ID | 成果物 | 完了判定 | 不確実性 |
| --- | --- | --- | --- |
| T-01 | 判定・状態・削除manifestの純粋関数 | 検査: `uv run pytest backend/tests/test_file_ingestion.py` | 類推可能 |
| T-02 | fake extractorの抽出契約 | 検査: 同テストで必須メタデータを確認 | 類推可能 |
| T-03 | 20件評価表 | 検査: 表の20行とテスト分類をレビュー | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| 形式検査 | 拡張子とマジックバイトの双方を確認する | MIME自己申告だけは偽装できるため却下 | 安全側の早期拒否 |
| 画像PDF | 受入可能・`needs_ocr`で検索不可 | OCRを初回実装する案は外部依存と品質評価が未完のため却下 | OCR候補として記録 |
| 削除 | 四種別のmanifestを先に固定する | 原本だけの削除は索引残存を招くため却下 | 実ストレージPRの契約とする |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | 初版 | SP-03の安全性・抽出品質を固定 | T-01からT-03 |
