# Founder Graph attachment store remediation plan

最終検証日: 2026-09-22

## 位置づけと対象

本書は、[Founder Graphピボット計画](founder-graph-pivot.md)のT-FG-04 `content-addressed attachment store`について、3巡目レビューで確定した4件の安全性指摘を実装前の2 bounded sliceへ再分解する補足計画である。T-FG-04のhash、dedupe、論理削除、purge、metadata契約は維持し、path、descriptor、reparse、例外境界だけを補強する。

対象実装は [founder_graph_attachments.py](../../backend/dots/founder_graph_attachments.py)、対象テストは [test_founder_graph_attachments.py](../../backend/tests/test_founder_graph_attachments.py) とする。このturnではコード、既存テスト、fixtureを変更せず、本計画ファイルだけを作成する。commit、PR、handoffは行わない。

### 現行baseline

3巡目レビューで確認済みのfocused suiteをbaselineとする。

| 環境 | コマンド | baseline |
| --- | --- | --- |
| Windows | `uv run pytest backend/tests/test_founder_graph_attachments.py -q` | 16 passed, 1 skipped |
| WSL native Linux | `uv run pytest backend/tests/test_founder_graph_attachments.py -q` | 17 passed |

新しい回帰テストは既存17件を置き換えず、実装前にRED、実装後に同じpytest nodeでGREENを記録する。Windows専用テストはWSLで理由付きskip、POSIX専用テストはWindowsで理由付きskipとし、対象プラットフォームでの新規skipは許可しない。

## 要望 / ゴール / 成功指標

### 要望

T-FG-04の3巡目レビューで確定した次のfindingを、実装者が再解釈せず検証できる契約へ落とし込む。

1. Medium: Windows `put_file`が最終fileだけをreparse検査しており、親junctionによるescapeを防げない。全親componentをpre/post検査する。
2. Medium: POSIXのobject、metadata、source openがFIFOをregular判定する前にblockし得る。`O_NONBLOCK`とdescriptorの`fstat`でfail-closedにする。
3. P2: Windowsのquarantine、replace、unlinkにpost-reparse contractがない。same-account hostile process raceはout-of-scopeのまま、文書と実装契約を一致させる。
4. P2: POSIX symlink / `ELOOP` のraw `OSError`を`AttachmentSecurityError`へ正規化する。

### ゴール

untrusted caller pathと非regular filesystem nodeを、WindowsとPOSIXの両方でboundedな失敗として扱い、T-FG-04のcontent-addressed dataをroot外へ読み書きしないattachment storeにする。

### 成功指標

4件のRED testが実装前に現行コードで失敗し、実装後に同じnodeでGREENとなり、Windowsでは全親componentのpre/post reparse検査、POSIXでは3種類のFIFO read阻止とsymlink/`ELOOP`例外正規化を観測できる。既存baselineのhash、dedupe、delete、purge契約は回帰しない。

## 確定findingと回帰テスト

| ID | severity | 確定した不備 | RED test node |
| --- | --- | --- | --- |
| AR-F1 | Medium | Windows `put_file`が終端source fileだけを検査し、親junction / reparse componentを検査しない | `backend/tests/test_founder_graph_attachments.py::test_windows_put_file_rejects_parent_junction_escape_before_and_after_read` |
| AR-F2 | Medium | POSIX object、metadata、sourceのdescriptor openがFIFOをregular判定する前にblockし得る | `backend/tests/test_founder_graph_attachments.py::test_posix_object_metadata_and_source_fifo_opens_fail_closed_without_blocking` |
| AR-F3 | P2 | Windows quarantine、`os.replace`、unlink後のdestination / parent reparse状態を契約化していない | `backend/tests/test_founder_graph_attachments.py::test_windows_quarantine_replace_and_unlink_recheck_parent_reparse_contract` |
| AR-F4 | P2 | POSIX symlink / `ELOOP`のraw `OSError`がstore境界から漏れる | `backend/tests/test_founder_graph_attachments.py::test_posix_symlink_and_eloop_are_normalized_to_attachment_security_error` |

## ユーザーストーリーと受け入れ条件

### US-AR-1 POSIX FIFOをblockさせない

As a local attachment-store maintainer, I want object, metadata, and source descriptors opened non-blocking and checked with `fstat` before reads, so that a FIFO cannot hang the local process.

RED test: `test_posix_object_metadata_and_source_fifo_opens_fail_closed_without_blocking`

Given: WSL native Linuxでobject path、metadata / journal readerへ渡すpath、`put_file` source pathをそれぞれFIFOに置き、writerを接続しない。

When: `_read_object()`、`_read_file_bytes()`、`_read_source_once()`を各pathへ呼ぶ。

Then: 各呼出しはwriter待ちなしでbounded timeout内に`AttachmentSecurityError`を返し、`os.read`はregular判定後だけ実行され、object、sidecar、transaction markerを新規作成しない。

- 脅威モデル: callerまたは同一local workspaceの入力がFIFOを配置し、`O_RDONLY`のblocking openでworkerを停止させる。
- 非目標: FIFOを通常fileへ変換すること、FIFOの内容を読み取ること、Windows named pipeをPOSIX契約へ持ち込むこと。

### US-AR-2 POSIXのsecurity errorを統一する

As a local attachment-store caller, I want symlink and `ELOOP` failures translated at the store boundary, so that callers never need to handle raw platform-specific path errors.

RED test: `test_posix_symlink_and_eloop_are_normalized_to_attachment_security_error`

Given: WSL native Linuxでobject、metadata、sourceまたはそのparentにsymlinkを置き、descriptor walkまたは`O_NOFOLLOW` openが`ELOOP`になる。

When: 対応するread、metadata、または`put_file`を呼ぶ。

Then: raw `OSError` / `errno.ELOOP`は公開されず、`AttachmentSecurityError`へ正規化される。`ENOENT`は従来どおり`AttachmentMissingError`であり、metadata corruptionは`AttachmentMetadataError`のままになる。

- 脅威モデル: symlinkまたはsymlink chainがroot外のfile、directory、FIFOへdescriptor walkを誘導する。
- 非目標: すべてのPOSIX `OSError`をsecurity errorへ変換すること。missing、integrity、metadataの既存分類を壊さない。

### US-AR-3 Windows source pathの全componentを検査する

As a Windows attachment-store maintainer, I want every existing parent component of a `put_file` source path checked before and after the descriptor read, so that a parent junction cannot redirect the source read outside its intended path.

RED test: `test_windows_put_file_rejects_parent_junction_escape_before_and_after_read`

Given: Windowsでsourceの終端fileはregularだが、source pathのparent componentがjunctionまたはreparse pointとして外部targetへ解決する。

When: `put_file()`がsourceを開いてhashし、closeした後にcommitへ進もうとする。

Then: source pathのfilesystem anchorから終端fileまでの全parent componentと終端fileをpre/postで検査し、reparse componentを検出した時点で`AttachmentSecurityError`を返す。object、metadata、transaction markerを外部targetへ作成しない。

- 脅威モデル: callerがsource pathのparent junctionを差し替え、終端fileだけの検査を通過させて別locationを読み込ませる。
- 非目標: 正常なregular sourceのhash、metadata、dedupe semanticsを変更すること、same-account hostile processのraceをkernel-levelで封じること。

### US-AR-4 Windows mutationのpost-reparse contractを固定する

As a Windows attachment-store maintainer, I want quarantine, replace, and unlink to verify their affected parents and endpoints after mutation, so that a completed mutation is not accepted while its path contract is invalid.

RED test: `test_windows_quarantine_replace_and_unlink_recheck_parent_reparse_contract`

Given: Windowsでquarantine destination、atomic replace target、またはunlink対象のparent / endpointにreparse状態を注入する。

When: `_quarantine_one()`、`_atomic_write()`のreplace、または`_remove()`のunlinkが完了する。

Then: source parent、destination parent、replace target、unlink parentのpost状態を検査し、reparseまたはroot外解決を`AttachmentSecurityError`として返す。正常なmutationだけがjournal完了へ進む。同一accountのhostile processによるcheck間raceは文書上のout-of-scopeを維持する。

- 脅威モデル: callerがmutation対象またはdestinationのparentをjunction / reparse pointへ変更し、quarantineやtemporary cleanupの後にpath boundaryを破る。
- 非目標: same-account hostile processへの完全なTOCTOU防御、Windows ACLの自動設定、filesystem transactionの新設。

## 共通脅威モデルと不変条件

### 脅威モデル

- in-scope: untrusted callerが渡すpath、path traversal、symlink、junction、reparse point、FIFO、symlink chain、metadata/object/sourceの非regular node。
- in-scope: 協調するstore instance間のjournal、quarantine、atomic replace、unlink後に観測できるpath boundary不整合。
- out-of-scope: 同じWindows accountを制御するnon-cooperating hostile processがcheckの間にpathをraceするkernel capability boundary、ACL変更、第三者への外部送信。

### 不変条件

1. Windowsのsource readはfilesystem anchorからsource endpointまで、mutationはstore rootからaffected endpointまで、全parent componentとendpointをpre/postで検査し、reparseまたは意図した境界外の解決を受け入れない。
2. POSIXのobject、metadata、source descriptorは`O_NOFOLLOW`と`O_NONBLOCK`を使い、最初の`os.read`より前にdescriptorの`fstat`でregular fileを確認する。
3. POSIXのsymlink / `ELOOP`は`AttachmentSecurityError`、missingは`AttachmentMissingError`、bytes/size不一致は`AttachmentIntegrityError`、sidecar形式不正は`AttachmentMetadataError`に分類する。
4. security failure後に新しいobject、metadata、transaction markerを採用せず、既存journal recoveryのfail-closed順序を保つ。

## 実装タスク: 2 bounded slices

| ID | bounded slice | 成果物と完了判定 | 不確実性 |
| --- | --- | --- | --- |
| AR-R1 | POSIX descriptor safety and error normalization | `founder_graph_attachments.py`のobject、metadata、source openを`O_NONBLOCK` + `fstat`先行へ更新し、symlink / `ELOOP`を`AttachmentSecurityError`へ正規化する。検査: AR-F2、AR-F4のRED test node、既存attachment suite、`python -X utf8 -m py_compile backend/dots/founder_graph_attachments.py`、`git diff --check`。 | 類推可能 |
| AR-R2 | Windows component and mutation reparse contract | `put_file`のsource parent chain、quarantine、replace、unlinkのaffected parent / endpointを共通pre/post検査へ揃え、same-account hostile processはout-of-scopeとmodule docへ明記する。検査: AR-F1、AR-F3のRED test node、既存attachment suite、Windows/WSL inspection、`python -X utf8 -m py_compile backend/dots/founder_graph_attachments.py`、`git diff --check`。 | 類推可能 |

### AR-R1の境界

- 変更対象: `_read_object()`、`_read_file_bytes()`、`_read_source_once()`、POSIX descriptor helper、security exception adapter、対応するpytest fixture。
- `fstat`はopen直後かつread loopより前に行い、FIFO、socket、directory、deviceを拒否する。regular fileのread後size checkと既存hash検証は維持する。
- `ELOOP`だけを理由なく一括catchせず、`ENOENT`とmetadata decode failureの既存error contractを保存する。

### AR-R2の境界

- 変更対象: Windows source path inspection、`_quarantine_one()`、`_atomic_write()`のreplace後検査、`_remove()`のunlink後検査、affected parent helper、対応するpytest fixtureとmodule threat-model docstring。
- parent inspectionはfinal endpointだけで終えず、operationが触るsource parent、source endpoint、destination parent、destination endpointを同じcontractで検査する。
- post-checkで失敗した場合はjournal完了を返さず、既存recovery pathでorphanを採用しない。

AR-R1を先にGREENへし、次にAR-R2へ進む。各sliceは実装差分500行以内、review 30分以内を目安とし、他のFounder Graph module、API、UI、local-opsを変更しない。

## 質問リスト

| ID | 質問 | 決定 | 決定者 | 期限 |
| --- | --- | --- | --- | --- |
| Q-AR-01 | 追加の仕様決定 | なし。4件のfinding、severity、same-account hostile processのout-of-scope境界は3巡目レビューで確定済み | 利用者兼製品責任者 | 2026-09-22 |

## スコープ外

- T-FG-04のhash、dedupe、metadata immutability、reference、logical delete、undelete、purge semanticsの変更。
- Neo4j schema、FastAPI、MCP transport、ChatGPT接続、UI、外部AI、credential、個人情報送信の変更。
- Windows ACLの自動設定、reparse pointのkernel-level race解消、同一accountのnon-cooperating hostile processを防ぐ保証。
- 新しいfilesystem transaction、DB migration、storage format migration、既存objectの一括移行。
- `docs/inherited/`、local-ops runbook、Compose、Bash、PowerShell helperの変更。
- このturnでのコード、既存テスト、fixture、commit、PR、handoff。

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 / 見直し条件 |
| --- | --- | --- | --- |
| ADR-AR-01 POSIX open | `O_NONBLOCK`を付けてopenし、descriptorの`fstat`でregular fileをread前に確認する。FIFO openのblockを防ぎ、object、metadata、sourceで同じ契約を使える。 | pathの`is_file()`を先に呼ぶ案はcheckとopenの間にnodeが変わり、FIFOのblocking openも止められないため却下。 | AR-R1で3 surfacesを同じfixtureから検証する。非POSIX branchは既存Windows契約を壊さない。 |
| ADR-AR-02 Windows component boundary | source readとmutationごとに関係する全parent componentとendpointをpre/post検査する共通helperを使う。final fileだけの検査を廃止し、journal完了前にpost状態を確定する。 | final endpointだけを見る案はparent junction escapeを検出できず、operationごとに別実装する案はquarantine、replace、unlinkの契約を分岐させるため却下。 | AR-R2でsource、quarantine、replace、unlinkを同じ境界語彙で記録する。race防御の追加要求が出た場合は別ADRへ戻す。 |
| ADR-AR-03 exception boundary | POSIX symlink / `ELOOP`を`AttachmentSecurityError`へ寄せ、`ENOENT`、integrity、metadata errorは既存分類を維持する。 | 全`OSError`をsecurity errorへ変換する案はmissingとI/O障害の診断を失うため却下。 | AR-R1のerror matrixでraw platform exception 0件を確認する。 |
| ADR-AR-04 slice layout | POSIX read/errorをAR-R1、Windows path/mutationをAR-R2へ分け、各sliceに対応RED testを置く。 | 4 findingを1つの広い修正へまとめる案はレビュー境界とrollback境界を失い、500行上限を超える恐れがあるため却下。 | AR-R1 GREENがAR-R2の開始条件になる。 |

## ロールバック

| finding | rollback boundary |
| --- | --- |
| AR-F1 | AR-R2だけをrevertし、Windows `put_file`のjunction RED testを未解決としてsource intakeをrelease gateから外す。既存objectとmetadataは保持する。 |
| AR-F2 | AR-R1だけをrevertし、POSIX FIFO RED testを未解決としてobject、metadata、sourceの対象readを再開しない。 |
| AR-F3 | AR-R2だけをrevertし、quarantine、replace、unlinkのpost-reparse RED testを未解決としてmutation releaseを止める。journalとquarantineの既存データは保持する。 |
| AR-F4 | AR-R1だけをrevertし、symlink / `ELOOP` RED testを未解決としてraw platform errorを許容するreleaseを行わない。missing、integrity、metadataの既存分類を保存する。 |

- AR-R1とAR-R2は独立した実装単位として適用し、失敗時は該当sliceの差分だけをrevertする。既存object、metadata、transaction journalを物理削除せず、storage formatは変更しない。
- AR-R1のrollback中はFIFOと`ELOOP` RED testを未解決として扱い、POSIX attachment intakeを再開しない。既存のmissing、integrity、metadata error分類を比較してから再試行する。
- AR-R2のrollback中はWindows `put_file`、quarantine、replace、unlinkのpost-reparse RED testを未解決として扱い、影響するmutationをrelease gateから外す。same-account raceを解決済みと報告しない。
- rollback判断はテスト失敗をskipへ変更して通過させず、baselineデータのhashとmetadataを照合してから行う。

## Windows / WSL検査計画

### Windows

1. `uv run pytest backend/tests/test_founder_graph_attachments.py -q`で既存baselineの16 passed / 1 skippedを確認する。
2. AR-F1とAR-F3の2 nodeをWindowsで実行し、junction / reparse fixtureがskipされず、`AttachmentSecurityError`、外部targetへのobject / metadata作成0件、post-check失敗のjournal未完了を確認する。
3. `python -X utf8 -m py_compile backend/dots/founder_graph_attachments.py`と`git diff --check`を実行する。

### WSL native Linux

1. `uv run pytest backend/tests/test_founder_graph_attachments.py -q`で既存baselineの17 passedを確認する。
2. AR-F2とAR-F4の2 nodeをWSLで実行し、3種類のFIFO openがbounded timeout内にfail-closedし、symlink / `ELOOP`のraw `OSError`が0件であることを確認する。Windows専用AR-F1、AR-F3は理由付きskipとする。
3. `python -X utf8 -m py_compile backend/dots/founder_graph_attachments.py`と`git diff --check`を実行する。

### 計画文書の検査

- 禁止曖昧語: `rg -n '\x{306A}\x{3069}|\x{67D4}\x{8EDF}\x{306B}|\x{3044}\x{3044}\x{611F}\x{3058}\x{306B}|\x{9069}\x{5207}\x{306B}|\x{5FC5}\x{8981}\x{306B}\x{5FDC}\x{3058}\x{3066}|\x{53EF}\x{80FD}\x{306A}\x{9650}\x{308A}' docs/plans/founder-graph-attachment-remediation.md` が0件。
- 相対リンク: 本書の相対リンク3件を、計画所在ディレクトリから解決して `Test-Path -LiteralPath` がすべてtrueになることを確認する。
- 文書差分: `git diff --check -- docs/plans/founder-graph-attachment-remediation.md` を実行し、空白エラー0件とする。実装PRではコード、test、docを含む全差分へ同じ検査を広げる。
- 差分上限: 実装sliceごとに`git diff --stat`を確認し、500行以下、目的1件、review 30分以内を満たす。

## Exit Criteria

- 4つのRED test node名がこの計画と実装PRで一致し、各nodeの実装前REDと実装後GREENの記録がある。
- AR-F1はsourceの全parent componentをpre/post検査し、parent junction escapeと外部targetへの保存を拒否する。
- AR-F2はobject、metadata、sourceのFIFOをread前にregular判定し、blockしない。
- AR-F3はquarantine、replace、unlinkのaffected parent / endpointをpost検査し、journal完了前にsecurity errorを返す。same-account hostile processはout-of-scopeと文書化されている。
- AR-F4はPOSIX symlink / `ELOOP`を`AttachmentSecurityError`へ正規化し、`ENOENT`、integrity、metadata errorを維持する。
- Windows baseline 16 passed / 1 skipped、WSL baseline 17 passedを比較基準として、既存T-FG-04 contractに新規回帰がない。
- WindowsとWSLのfocused inspection、`py_compile`、`git diff --check`が成功し、対象platformでの新規skipがない。
- 禁止曖昧語0件、相対リンク解決成功、各実装slice差分500行以下を確認する。
- T-FG-04以外のproduct/API/storage format変更、実データ、外部接続、commit、PRを完了根拠にしない。

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-09-22 | T-FG-04の3巡目レビュー確定finding 4件を、4 RED testと2 bounded sliceへ分解し、Windows/WSL baseline、脅威モデル、rollback、Exit Criteriaを追加 | attachment storeのsecurity contractを実装前に固定するため | AR-R1、AR-R2 |
