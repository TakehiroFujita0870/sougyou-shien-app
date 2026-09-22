# Founder Graph offline backup / restore manifest 計画

最終検証日: 2026-09-22

## 要望 / ゴール / 成功指標

要望: Dotsのowner-scopedな決定的JSON exportを、ローカル保管用manifestで検証し、Docker、Neo4j、ネットワーク、削除操作なしでrestore dry-runを実行できる契約を追加する。

ゴール: exportのschema、owner境界、ノード数、関係数、サイズ、hash、相対pathを検査し、同一manifestとexportを再検証できる安全なoffline backup / restore入口を提供する。

成功指標: 正常なmanifestが決定的exportのSHA-256、schema version、node / relation counts、owner、相対pathを一致検証し、変更、symlink、path traversal、owner不一致、schema不一致をDocker起動前に拒否する。dry-runはファイルを作成、上書き、削除せずに検証結果を返す。

## ユーザーストーリーと受け入れ条件

### US-BR-01 owner-scoped export manifest

As a 単独利用者, I want safe JSON exportからowner単位のbackup manifestを作りたい, so that 復元対象と内容の同一性を検査できる。

Given: `founder-graph-export-v1`のowner付きJSONに一意なnodeとrelationがあり、export内容がcanonical JSONである

When: offline validatorがmanifestを作成または検証する

Then: manifestはmanifest schema version、export schema version、owner ID、相対export path、byte count、SHA-256、node count、relation countを保持し、同じ入力から同じJSONを生成する

### US-BR-02 path and integrity boundary

As a 単独利用者, I want backup pathと内容の境界を検証したい, so that symlink経由の読み取りや別ownerの混入を防げる。

Given: manifestまたはexportがsymlink、root外、絶対export path、`..`を含むpath、hash不一致、owner不一致、schema不一致である

When: validatorがmanifestを読み込む

Then: Docker、Neo4j、外部通信、ファイル変更を行わず、ContractErrorとして拒否する

### US-BR-03 non-destructive restore dry-run

As a 単独利用者, I want restore前にbackupの整合性をdry-runしたい, so that live dataを変更せず復元可否を判断できる。

Given: manifestと参照exportが安全なbackup root内にあり、hash、schema、owner、countsが一致している

When: restore dry-runを実行する

Then: verified状態、owner、node count、relation count、検証済みpathを返し、Docker/Neo4jを呼ばず、既存ファイルを作成、上書き、削除しない

## 質問リスト

なし。初期sliceではsafe JSON exportのoffline検証に限定し、Neo4j dumpの実loadは後続gateで扱う。

## スコープ外

- Docker daemon、Neo4j、MCP、ネットワークへの接続。
- `neo4j.dump`または`system.dump`の作成、load、volume操作。
- 既存manifest、export、backupファイルの上書き、削除、移動。
- 暗号化、圧縮、クラウド転送、スケジューラー。
- private、local_only、contact、instruction pathを含むexportの許可。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-BR-01 | deterministic export envelopeとmanifest schemaのvalidator | 検査: schema、owner、node / relation count、byte count、SHA-256、canonical orderingをfocused pytestで検証する | 既知 |
| T-BR-02 | safe path resolverとsymlink / traversal拒否 | 検査: absolute root、relative export path、symlink、root外、`..`、欠落fileをfocused pytestで検証する | 類推可能 |
| T-BR-03 | non-destructive restore dry-run APIとCLI | 検査: Docker/Neo4j未起動環境でdry-runが成功し、filesystem snapshotが変化しないfocused pytestを実行する | 既知 |
| T-BR-04 | local ops検査と実装メモ | 検査: `py_compile`、focused pytest、`git diff --check`、static local ops validatorを実行し、結果を本書へ記録する | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| ADR-BR-01 export envelope | top-levelにexport schema version、owner ID、nodes、relationsを置き、manifestはownerと相対pathを固定する | raw Neo4j dumpだけをmanifest対象にする案はowner projectionとJSON差分を検査できないため却下 | safe JSONをoffline restore gateへ接続できる |
| ADR-BR-02 hash | raw export byte SHA-256とcanonical JSONの一致を検証し、manifestのbyte countとnode / relation countを照合する | node countだけを比較する案は内容改変と順序差を検知できないため却下 | 内容、サイズ、構造の不一致を同時に拒否できる |
| ADR-BR-03 path safety | backup rootを既存の絶対非symlink directoryに限定し、export pathはroot相対POSIX pathに限定する | 任意絶対pathをmanifestから直接読む案はroot外、traversal、symlinkを許すため却下 | restore dry-runの読み取り境界を固定できる |
| ADR-BR-04 restore behavior | dry-runは読み取りと検証だけを行い、ファイル変更とDocker起動を行わない | dry-run中にrestore volumeを作る案は破壊・外部依存の境界を広げるため却下 | Docker実機gateの前に安全な静的検証ができる |

## 実装メモ

- 計画タスク: T-BR-01〜04
- 受け入れ条件: US-BR-01〜03
- 追加成果物: `scripts/founder-graph/verify_export_backup.py` に、safe JSON exportのcanonical JSON、owner、schema、node / relation count、byte count、SHA-256、root相対POSIX pathを検査する純粋なmanifest builder / verifierを追加した。`create`、`verify`、`dry-run` CLIはいずれもDocker、Neo4j、ネットワーク、外部モデルを呼ばず、manifestは`O_EXCL`で新規作成だけを許可する。
- dry-run結果: `status=verified`、owner、検証済み相対path、byte count、SHA-256、node / relation countを返す。manifestのowner、export schema、canonical順序、hash、count、symlink、traversal、forbidden private/local-only field、重複node IDを拒否する。
- 追加テスト: `backend/tests/test_founder_graph_backup_manifest.py`（9 passed, 1 skipped）、既存local-opsを含むfocused実行（32 passed, 3 skipped）。`python scripts/founder-graph/validate_local_ops.py --root .` は `PASS (static, Docker-free)`。
- 監査注記: 現行helperはexport top-levelの`owner_id`が欠落したsafe exportも受理し、`build_manifest`のowner引数をmanifest境界として結び付ける。したがってmanifestのownerは検証呼出しの入力であり、export bytes単独からowner provenanceを証明するものではない。US-BR-01とADR-BR-01の「owner付きJSON」要件をfull owner backupの完了根拠にしない。
- エラー分類: path、schema、owner、hash、countの不一致は入力修正が必要なvalidation error。I/O失敗は呼出元が再試行する回復可能エラー。partial outputは返さない。
- API互換性: 新規offline scriptのみ。既存MCP、FastAPI、Neo4j adapter、UIは変更しない。
- 外部通信: なし。
- ループ周回数: 2。Docker/Neo4j実機restoreは未検査で、後続のlive gateに残す。

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-09-22 | owner-scoped JSON export、manifest、path safety、dry-runのG/W/TとADRを定義 | T-FG-01 / T-FG-03の実機restore前にDocker-free検証を分離するため | T-BR-01〜04 |
| 2026-09-22 | offline manifest builder / verifier、非破壊dry-run、focused tests、local-ops static gateを実装 | 実機Docker gateの前にsafe exportの復元可否を検証できるようにするため | T-BR-01〜04 |
