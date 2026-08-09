# Knowledge ローカル資料追加 計画

最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

要望: Knowledge の「資料を追加」を、固定デモ資料を復元する操作から端末上の資料を選択する操作へ置き換える。

ゴール: ユーザーが PDF または DOCX を選択し、ファイル本体を保存・送信せずに owner/space 固定のメタデータだけを Knowledge に追加できる。

成功指標: 同じファイル選択は重複表示されず、再読込後にも追加・削除状態が再現され、失敗時に状態を偽らない。

## ユーザーストーリーと受け入れ条件

### US-1

As a 起業準備中の利用者, I want PDF または DOCX を Knowledge から選択したい, so that 手元資料を後続の検討対象として把握できる。

Given: Knowledge を開いている
When: 10 MiB 以下の PDF または DOCX を選択する
Then: ファイル名、サイズ、端末内メタデータ状態が表示され、ファイル本文は localStorage に書き込まれない。

### US-2

As a 起業準備中の利用者, I want 選択した資料の状態を再読込後にも確認したい, so that 追加作業を繰り返さずに済む。

Given: owner/space の資料メタデータが保存されている
When: ページを再読込する
Then: 同じ owner/space の資料だけが表示され、削除済み資料は表示されない。

### US-3

As a 起業準備中の利用者, I want 誤った資料選択を理解して修正したい, so that 実際には追加されていない状態を成功と誤認しない。

Given: PDF/DOCX 以外、10 MiB 超、または保存失敗が発生する
When: 資料を選択する
Then: 資料一覧を変更せず、次に取る行動が分かるエラーを表示する。

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| なし | 本PRのローカルメタデータ追加に未決事項はない | CEO室 | 2026-08-09 |

## スコープ外

- ファイル本文、抽出本文、埋め込みの保存または外部送信。
- PDF/DOCX の内容解析、検索、AI応答、実外部ストレージ接続。
- Home、Project、Account、Plan の変更。
- モバイルレイアウトの最適化。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-1 | metadata-only 状態と決定的ローカルIDを持つrepository | 検査: `npm run test -- knowledgeMetadataRepository` | 既知 |
| T-2 | Knowledge のfile picker、一覧、削除、エラー表示 | 検査: `npm run test -- KnowledgeSurface` | 類推可能 |
| T-3 | Appから固定fixture復活callbackを除去 | 検査: `npm run test -- App` | 既知 |
| T-4 | 1440px Storyと全体検査 | 検査: `npm run test; npm run build; npm run build-storybook; uv run pytest; git diff --check` | 類推可能 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| 保存単位 | owner/space付きファイルメタデータだけをlocalStorageへ保存する。本文を持たず、外部送信境界を越えない。 | File/BlobをlocalStorageへ保存: 容量・プライバシー・復元保証を誤認させるため却下。 | `metadata_only`状態を導入する。 |
| 重複ID | name、size、lastModifiedから安定IDを作る。 | 毎回UUID: 同じ選択を重複表示するため却下。 | 同一メタデータの再選択は更新扱いにする。 |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | 初版 | 死にUIだった資料追加を実操作へ置換 | T-1〜T-4 |
