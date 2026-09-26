# Founder Graph MCP tool annotation completeness plan

最終検証日: 2026-09-26

## 要望 / ゴール / 成功指標

要望: Founder Graph のFastAPIとstdioが、登録済みの各MCPツールについて、読み取り専用性・既存記録への影響・外部世界への作用を正確に同じ形で示す。

ゴール: 共通の注釈を両transportのツール一覧に公開し、既存ツールと`capture_source`の副作用分類を一貫させる。

成功指標: FastAPIとstdioの全ツール名が一致し、各ツールの`readOnlyHint`、`destructiveHint`、`openWorldHint`が同じ真偽値で、期待する分類に一致する。

## ユーザーストーリーと受け入れ条件

### US-1 呼び出し前にツールの作用を判別する

As a Founder Graph MCP caller, I want each listed tool to provide truthful side-effect annotations, so that I can distinguish reads, writes, and destructive changes before calling it.

Given: 同じ合成ownerで起動したFastAPIとstdioのFounder Graph MCP catalogがある。
When: FastAPIの`/v1/founder-graph/mcp/tools`とstdioの`tools/list`を読む。
Then: ツール名が一致し、すべてのツールにbooleanの`readOnlyHint`、`destructiveHint`、`openWorldHint`が存在し、両transportで値が一致する。`search`と`fetch`は`true/false/false`、全write toolは`false/<個別分類>/false`である。`capture_source`は`false/false/false`で、説明と引数schemaがページ取得・調査を開始しない契約を保つ。

### US-2 既存記録を置換しうる操作を明示する

As a Founder Graph MCP caller, I want corrections and person merges that replace existing records clearly marked as destructive, so that I do not mistake them for append-only writes.

Given: 現在のwrite tool definitionsを読む。
When: 作用の分類を確認する。
Then: `record_correction`と`confirm_person_merge`は`destructiveHint=true`である。`link_entities`は既存関係を置換せず追加するためfalseであり、他の既存create/append toolもfalseである。分類対象外の未配送research toolはcatalogに追加されない。


## 質問リスト

なし。既存の承認済み分類を共通helperへ移し、ツールの保存動作、公開境界、権限を変更しない。

## スコープ外

- 新しいMCP tool、research workflow、HTTP route、権限、認証、runtimeまたはDB変更。
- 既存の日本語説明、input/output schema、保存・訂正処理の意味変更。
- 登録済みChatGPT pluginのrefreshや外部接続を使った検証。
- FastAPIとstdio以外のtransportや外部公開。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| ANNOT-01 | 共通annotation helperとread/write定義への明示分類 | 検査: 新規catalog testが読み取り・破壊的write・通常write・`capture_source`を個別に分類し、未配送tool名がないことを確認 | 既知 |
| ANNOT-02 | FastAPIとstdioの3項目一致および既存回帰テスト | 検査: targeted metadata/API/stdio tests、全backend pytest、`git diff --check`が成功 | 類推可能 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| 注釈の所有元 | 読み取り・書き込みtool definitionが同じ小さなhelperで3項目のannotationを生成し、stdioはそのannotationをそのまま転送する。FastAPIは同じdefinitionを返す | FastAPIとstdioで個別に判定を複製する案はtransport間の不一致を許すため却下 | 両transportに同一の真偽値を返せる |
| destructive分類 | 実際に既存記録を置換する訂正・名寄せ確定のみtrueとする。`link_entities`は新しい関係と監査記録を追加するだけなのでfalseとする | tool名や関係の意味だけから置換動作を推測する案は誤分類になるため却下 | `capture_source`と`link_entities`を含むcreate/appendはfalse、既存記録を置換する操作はtrueとなる |
| open-world分類 | 現行private local catalogの全read/writeでfalseを明示する | 項目を省略してtransport既定値へ委ねる案はconsumer差を生むため却下 | MCP consumerが外部作用の有無を確実に判別できる |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-09-26 | 3項目のMCP tool annotationsをtransport間で統一する計画を追加 | `capture_source`を含む既存カタログの作用情報を明示するため | ANNOT-01、ANNOT-02 |
| 2026-09-26 | `link_entities`の破壊的分類をfalseへ修正 | 実装は既存関係の置換ではなく関係と監査記録の追加であるため | ANNOT-01、ANNOT-02 |
