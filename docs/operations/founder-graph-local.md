# Founder Graph ローカル Neo4j 運用

最終検証日: 2026-09-23

## 範囲

この運用は、本人一人がWindows上のDocker Desktop（またはWSL2から見える同じDocker Engine）で使うFounder Graph開発用Neo4jだけを対象にする。
ComposeはHTTPとBoltを`127.0.0.1`へだけ公開する。コンテナ間の内部ネットワークは外部接続不可のまま保ち、Docker Desktopでポートを公開するために同じCompose project内の別ネットワークも併用する。
既存Postgres、既存データ、ChatGPT接続、MCP tunnel、外部サービスはこの手順の対象外である。
実データや実credentialをリポジトリへ置かない。

## 前提とcredential

- Windows PowerShellまたはWSL2のLinux native checkoutで実行する。Docker DesktopとDocker Compose v2が必要。WSL integrationが無い場合はWindows側のDocker CLIを使う。
- Neo4j Communityイメージ`neo4j:5.26-community`が利用できることを確認する。イメージ取得は利用者が許可した環境で別途行い、このrunbookは外部接続を開始しない。
- `FOUNDER_GRAPH_NEO4J_AUTH`へ、この端末だけで使う値を環境変数として設定する。形式は`neo4j/<local-password>`とし、実際のパスワードはコマンド履歴、ログ、Gitへ残さない。helperは`start`中だけComposeが参照し続けられる端末内の非公開secret fileを作り、`stop`で削除する。backupなど一回限りの操作では操作終了時に一時secret fileを削除する。credentialをDocker argv、`docker inspect`、ログへ渡さない。
- Composeへ渡す環境変数名は`FOUNDER_GRAPH_NEO4J_AUTH_FILE`である。これはhelperが作るsecret fileの場所だけを示し、パスワードそのものを示さない。
- Compose projectは`FOUNDER_GRAPH_COMPOSE_PROJECT`でnamespaceを指定できる。未設定時は`founder-graph-local`を使い、値は小文字のDocker project-name文字だけにする。

WSL bash:

```bash
export FOUNDER_GRAPH_NEO4J_AUTH='neo4j/<local-password>'
```

PowerShell:

```powershell
$env:FOUNDER_GRAPH_NEO4J_AUTH = 'neo4j/<local-password>'
```

`.env`やcredentialファイルを新規作成してコミットしない。Composeの`${...:?}`ガードにより、helperが作るsecret file以外を使った未設定のままの起動は失敗する。`start`で作られたsecret fileはコンテナ停止まで残り、`stop`で削除される。

## 構成とポート

| 用途 | 接続先 | 備考 |
| --- | --- | --- |
| Neo4j Browser / HTTP | `http://127.0.0.1:7474` | 同じ端末からのみ |
| Bolt | `bolt://127.0.0.1:7687` | 同じ端末からのみ |
| データ | `<project>_founder_graph_neo4j_data` | Compose project namespace付きvolume。`/data`へマウント |

`0.0.0.0`やLANアドレスへポートを変更しない。Neo4jサービスは`founder_graph_local`のinternal networkと、ポート公開用の同一project内networkに所属する。外部へ公開されるのはloopbackだけである。
live volumeには`com.openai.founder_graph.role=live` labelが付き、グローバル固定名を使わない。
Composeのhealthcheckはコンテナ内の`cypher-shell`で`RETURN 1`を実行する。

## 起動、health、停止

WSL bashからリポジトリルートで実行する。

```bash
bash scripts/founder-graph/founder-graph.sh validate
python scripts/founder-graph/migrate_schema.py --validate-only
bash scripts/founder-graph/founder-graph.sh start
bash scripts/founder-graph/founder-graph.sh status
docker compose --file compose.founder-graph.yml ps
```

`start`、backup後の再起動、manifest captureはhelperがhealth=`healthy`を待つ。`status`でhealthを再確認する。credentialをargvへ展開するraw `cypher-shell` password argumentは使わない。

T-FG-01の実機gateでは、合成fixtureのmanifestを停止前と再起動後に取得し、同じlive volumeのlabel、node / relationship count、代表queryのhashを比較する。停止と再起動は次の順序で行う。

```bash
fixture_dir='/mnt/c/Users/<you>/founder-graph-backups/tfg01'
bash scripts/founder-graph/founder-graph.sh capture-manifest \
  "$fixture_dir/queries.json" "$fixture_dir/before-stop.json"
bash scripts/founder-graph/founder-graph.sh stop
bash scripts/founder-graph/founder-graph.sh start
bash scripts/founder-graph/founder-graph.sh status
bash scripts/founder-graph/founder-graph.sh capture-manifest \
  "$fixture_dir/queries.json" "$fixture_dir/after-restart.json"
cmp -- "$fixture_dir/before-stop.json" "$fixture_dir/after-restart.json"
```

この手順はDockerが利用できるWSL2環境でだけ実行する。`stop`、`start`、`status`、manifest比較が成功し、volume名が同じであることを記録してT-FG-01の実機証跡とする。`down --volumes`、`docker volume rm`、volume pruneは使わない。

## Neo4j gatewayの接続境界

backendの`Neo4jGraphGateway`は、composition rootから明示的に渡されたNeo4j Python driverだけを使う。driverを生成する責務は通常起動のcomposition rootに限定し、gateway自体はNodeType / RelationTypeのallowlist、owner境界、idempotency audit、Campaign / Sourceのrevision historyをparameterized Cypherへ変換する。任意Cypherを受け取るAPIはない。

実機接続を行う場合は、Composeがhealthyになった後に、credentialを環境変数またはsecret managerから読み、コード・argv・ログへ展開しないcomposition rootからdriverを生成する。`create_neo4j_app()`または`create_neo4j_stdio_server()`へ同じowner-bound gateway compositionを明示注入できる。FastAPI通常起動（`dots.main:app`）とMCP標準起動は、`DOTS_GRAPH_BACKEND=neo4j`または`DOTS_NEO4J_PASSWORD`を指定した場合にNeo4jを通常保存先として選ぶ。単体テストでは`DOTS_GRAPH_BACKEND=memory`を明示できる。Neo4j接続情報が不足または接続不能な場合に黙って一時メモリへ切り替えない。

MCP標準起動をNeo4jへ向けるPowerShell例:

```powershell
$env:DOTS_GRAPH_BACKEND = 'neo4j'
$env:DOTS_LOCAL_OWNER_ID = 'owner-mvp'
$env:DOTS_NEO4J_URI = 'bolt://127.0.0.1:7687'
$env:DOTS_NEO4J_USERNAME = 'neo4j'
$env:DOTS_NEO4J_PASSWORD = '<same-local-password>'
```

MCPから検索結果を返す情報には`egress_policy=shareable`を明示する。`local_only`の情報は、誤って外部へ出さないためMCP検索結果から除外される。

```python
import os
from neo4j import GraphDatabase
from dots.main import create_neo4j_app

driver = GraphDatabase.driver(
    "bolt://127.0.0.1:7687",
    auth=("neo4j", os.environ["FOUNDER_GRAPH_NEO4J_PASSWORD"]),
)
app = create_neo4j_app(driver, "local-owner")
```

この例は接続境界の形を示すだけで、実credential、実データ、常駐接続をリポジトリへ追加しない。

停止は`stop`だけを使う。`down --volumes`、`docker volume rm`、volume pruneは使わない。

```bash
bash scripts/founder-graph/founder-graph.sh stop
```

再度`start`して同じvolumeが接続されることを確認する。停止・再起動は`founder_graph_neo4j_data`を削除しない。

PowerShellでは同じ操作を次で実行できる。

```powershell
.\scripts\founder-graph\founder-graph.ps1 validate
python .\scripts\founder-graph\migrate_schema.py --validate-only
.\scripts\founder-graph\founder-graph.ps1 start
.\scripts\founder-graph\founder-graph.ps1 status
.\scripts\founder-graph\founder-graph.ps1 stop
.\scripts\founder-graph\founder-graph.ps1 start
.\scripts\founder-graph\founder-graph.ps1 status
```

PowerShellでも、停止前と再起動後に`capture-manifest`を別の出力pathへ実行し、`Compare-Object`でmanifestの一致を記録する。実機結果がない状態でstatic validatorのPASSをlive PASSと扱わない。

## Backup drill

Backupは一貫性のためNeo4jを一時停止し、`neo4j-admin database dump neo4j`と
`neo4j-admin database dump system`を実行した後に必ず再起動する。
作成先はリポジトリ外の専用ディレクトリにする。既存のdump、非空ディレクトリ、symlink targetは拒否し、
`neo4j.dump`と`system.dump`を上書きしない。

```bash
backup_dir='/mnt/c/Users/<you>/founder-graph-backups/run-YYYYMMDD'
umask 077
mkdir -p -- "$backup_dir"
bash scripts/founder-graph/founder-graph.sh backup "$backup_dir"
test -s "$backup_dir/neo4j.dump"
test -s "$backup_dir/system.dump"
```

PowerShell:

```powershell
$backupDir = 'C:\Users\<you>\founder-graph-backups\run-YYYYMMDD'
.\scripts\founder-graph\founder-graph.ps1 backup -Path $backupDir
Test-Path -LiteralPath (Join-Path $backupDir 'neo4j.dump')
Test-Path -LiteralPath (Join-Path $backupDir 'system.dump')
```

## Restore drill（隔離volume）

Restoreは本番volumeへ上書きせず、新規の`founder-graph-restore-<lowercase-suffix>`名前付きvolumeへloadする。
helperは既存volume、live label、構成で明示したlive alias（完全一致）を拒否し、`foo-prod`のようなproject/source label内の語はidentity判定に使わない。loadコンテナには`--network none`を指定する。これにより、
restore演習中に外部へ接続せず、元のデータを削除しない。

```bash
backup_dir='/mnt/c/Users/<you>/founder-graph-backups/run-YYYYMMDD'
restore_volume='founder-graph-restore-yyyymmdd'
bash scripts/founder-graph/founder-graph.sh restore "$backup_dir" "$restore_volume"
```

PowerShell:

```powershell
$backupDir = 'C:\Users\<you>\founder-graph-backups\run-YYYYMMDD'
.\scripts\founder-graph\founder-graph.ps1 restore -Path $backupDir -RestoreVolume 'founder-graph-restore-yyyymmdd'
```

loadはNeo4j 5の形式で、`neo4j-admin database load neo4j --from-path=/backups --overwrite-destination=true`と
`neo4j-admin database load system --from-path=/backups --overwrite-destination=true`を順に実行する。
loadの終了コードが0であることを確認し、同じ合成fixtureで作ったmanifestを使って次のverificationを行う。

```bash
bash scripts/founder-graph/founder-graph.sh verify-restore \
  "$restore_volume" '/mnt/c/Users/<you>/founder-graph-backups/manifest.json'
```

manifestは`node_count`、`relationship_count`、3件の`representative_queries`、対応する3件の
64桁SHA-256 `query_hashes`を持つ。verificationは隔離volumeを`--network none`でbootし、ノード数、
関係数、3つの代表query結果hashを比較する。検証が終わるまで元volumeを廃止しない。
復元に失敗した場合もhelperは隔離volumeを保持するため、原因を確認してから次の新規volumeで再演習する。

backup pathとPowerShellのrestore sourceは絶対パス、リポジトリ外、`/data`外、非symlink、空ディレクトリである必要がある。
WSLでは作成時`umask 077`とmodeを検査し、world-readableなら停止する。PowerShellでは`Get-Acl`で
Everyone / Usersなどの広いread grantを拒否する。Docker `--mount`に渡すvolume名・pathのcommaも拒否する。
Windows ACL継承やWSL側親ディレクトリの権限は完全に同一視できないため、運用者は専用のローカルprivate
directoryを選ぶ。path検査はデータを削除せず、拒否時に既存ファイルを変更しない。

## Manifest capture

restore前に、稼働中の同じ合成fixtureから期待値を再現可能なJSONとして取得する。
queries JSONはread-only queryをちょうど3件持ち、結果の順序を`ORDER BY`などで固定する。
例えば`queries.json`を次の形にする。

```json
{"queries":[
  "MATCH (n:Idea) RETURN n.id ORDER BY n.id",
  "MATCH (n:Person) RETURN n.id ORDER BY n.id",
  "MATCH (a)-[r]->(b) RETURN a.id, type(r), b.id ORDER BY a.id, b.id"
]}
```

captureとverify-restoreは同じpositive query contractを使う。最上位は単一の`MATCH`または
`OPTIONAL MATCH`だけとし、`WHERE`、`WITH`、`RETURN`、必要な`ORDER BY`、`SKIP`、`LIMIT`だけを許可する。
`CALL`、`USE`、admin/write clause、未知のtop-level clause、コメント、セミコロン、多重statementは
Dockerを呼ぶ前に拒否する。コンテナ内の`cypher-shell`にも`--access-mode read`を指定し、credentialは
引き続きsecret fileから環境変数へ渡すだけでargvへ置かない。
禁止clause/tokenは括弧や角括弧の内側を含む全depthで検査し、subquery expressionやmap literalの`{}`も
拒否する。関数呼び出しは現在の代表queryに必要な純粋関数`count(...)`と`type(...)`だけを許可し、
namespace呼び出し、動的Cypher、APOCは許可しない。引用符内の`CALL`や`//`、`/*`などはliteralとして扱うが、
単一statement境界を優先する既存方針によりセミコロンはliteral内を含めて拒否する（この制約によるfalse rejectを許容する）。

captureは既存manifestを上書きせず、0600の新規ファイルへnode/relationship countと3件の
`query_hashes`を書き込む。Bash:

```bash
bash scripts/founder-graph/founder-graph.sh capture-manifest \
  '/mnt/c/Users/<you>/founder-graph-backups/queries.json' \
  '/mnt/c/Users/<you>/founder-graph-backups/manifest.json'
```

PowerShell:

```powershell
.\scripts\founder-graph\founder-graph.ps1 capture-manifest `
  -Path 'C:\Users\<you>\founder-graph-backups\queries.json' `
  -RestoreVolume 'C:\Users\<you>\founder-graph-backups\manifest.json'
```

captureとverificationのhashは、CRLF/CRをLFへ正規化する以外のresult whitespaceを保持する。
manifestに`expected_project`または`expected_source`を追加した場合、verificationはrestore volumeの
同名labelを完全一致で要求する。restore volumeは必ず`role=restore`かつ`database=neo4j`であり、
live volume key/aliasを含む名前やlabelは拒否する。

## Safe JSON export の offline backup manifest

Dotsのowner-scoped safe JSON exportは、Neo4j dumpとは別に、`founder-graph-backup-manifest-v1` manifestへ固定し、Dockerなしで検証できる。
`verify_export_backup.py`はcanonical JSON、export schema、owner、node / relation count、byte count、
SHA-256、root相対POSIX pathを検査する。private、local-only、contact、instruction path、symlink、
`..` traversalは拒否し、manifestは既存ファイルを上書きしない。

```bash
backup_root='/mnt/c/Users/<you>/founder-graph-backups/export-run'
python scripts/founder-graph/verify_export_backup.py create \
  --root "$backup_root" --export export.json --owner-id owner-1 --output manifest.json
python scripts/founder-graph/verify_export_backup.py dry-run \
  --root "$backup_root" --manifest manifest.json --owner-id owner-1 --json
```

`dry-run`は読み取りだけを行い、`status=verified`、owner、検証済み相対path、byte count、hash、
node / relation countを返す。これはNeo4j volumeの実loadではなく、T-BR-01〜04のDocker-free gateである。
実機のdump/load確認は従来の`backup`、`restore`、`verify-restore` drillで別途行い、static PASSをlive PASSと扱わない。

## Dockerなしの検査境界

`validate`と`backend/tests/test_founder_graph_local_ops.py`はCompose本文、ポート、healthcheck、
namespace付きvolume、credential参照、backup/restore/verify-restore/capture-manifest/verify-export-backupコマンド、runbookを静的に検査し、Docker daemonや
registryへ接続しない。`start`、health確認、backup dump、隔離volumeへのloadはDockerが利用できる環境で
別途実行し、その結果（ノード数、関係数、代表検索結果を含む）を記録する。従来はこの作業窓から実際のDocker smokeを利用できない状態だったが、現在はWindows側Docker Desktopで一部の実機確認を完了している。
2026-09-23にWindows側Docker Desktopで、Neo4j起動、schema migration、合成IdeaのMCP保存、停止・再起動、検索・取得までを実行済みである。これはlive smokeの一部であり、backup / restoreの実機確認はまだ行っていない。Docker smoke全体は未完了である。

監査時の判定は次のように分ける。

| 対象 | Docker-freeで確認する項目 | Docker実機で確認する項目 | 現在の状態 |
| --- | --- | --- | --- |
| T-FG-01 | loopback port、healthcheck、secret-file、start / status / stop、再起動手順、live volume非削除 | clean start、health、stop、restart、認証、同じvolumeのmanifest一致 | 起動・停止・再起動・MCP保存検索を実機確認、manifest一致は未実施 |
| T-FG-03 | neo4j / system dump・load、隔離label、`--network none`、3 query count / hash、read-only contract | dump生成、隔離volume load、node / relationship count、代表3問のhash一致 | static検査済み、実機未検査 |

実機gateの記録には、使用image tag、Compose project、volume名、各コマンドの終了コード、health、manifest比較、credential非露出、live volume非変更を含める。実機gateを通過するまでT-FG-01 / T-FG-03は完了扱いにしない。
