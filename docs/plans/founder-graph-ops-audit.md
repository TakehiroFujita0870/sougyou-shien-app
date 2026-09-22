# Founder Graph T-FG-01 / T-FG-03 運用監査計画

最終検証日: 2026-09-22

## 要望 / ゴール / 成功指標

要望: T-FG-01の起動・health・停止・再起動・volume永続化契約と、T-FG-03のdump・load・manifest・隔離restore検証契約を、既存のbash / PowerShell helper、Compose、runbook、Docker-free検査から監査する。

ゴール: Docker daemonへ接続しない検査で、両タスクの静的契約を同じ証跡へ束ね、実機gateが未実行であることをrunbookと計画へ明記する。

成功指標: static validator、focused pytest、Python syntax、Bash syntax、PowerShell parser、`git diff --check`が成功し、T-FG-01 / T-FG-03の静的検査済み項目と未実行の実機項目が分離して読める。

## ユーザーストーリーと受け入れ条件

### US-OA-01 ライフサイクル契約を監査する

As a 単独利用者, I want Founder Graphの起動、health、停止、再起動、volume永続化の契約を確認したい, so that 実機gateへ進む前に操作境界を読める。

Given: Compose、bash helper、PowerShell helper、local runbookがリポジトリに存在する

When: Docker-free validatorとfocused testを実行する

Then: loopback port、namespace付きlive volume、healthcheck、secret-file認証、`start` / `status` / `stop`、停止後の再起動手順、volume非削除方針が静的に検出される

### US-OA-02 backup / restore契約を監査する

As a 単独利用者, I want Neo4j dump、隔離volumeへのload、代表query検証の契約を確認したい, so that live volumeを変更せずrestore gateの準備状態を判断できる。

Given: `founder-graph.sh`、`founder-graph.ps1`、`verify_restore.py`、manifest capture scriptが存在する

When: Docker-free validatorとfocused testを実行する

Then: `neo4j` / `system`のdumpとload、restore label、`--network none`、3件の代表query、count、hash、read-only query contract、非破壊方針が静的に検出される

### US-OA-03 実機未検査の境界を明示する

As a 単独利用者, I want static PASSとlive PASSを区別したい, so that Docker未実行の状態をNeo4j実機の完了と誤認しない。

Given: 現在の検査環境でDocker daemonが利用できない

When: 監査結果とrunbookを読む

Then: static検査の成功、live start / health / stop / restart / dump / load / verifyの未実行、実機gateで採取すべき証跡が別々に記載される

## 監査結果の判定

| 対象 | 静的証跡 | 実機gate | 現在の判定 |
| --- | --- | --- | --- |
| T-FG-01 | Compose、両helper、validator、focused test、runbook | clean環境のstart、health、stop、restart、認証、同一volumeのデータ照合 | 静的検査済み。実機未検査 |
| T-FG-03 | dump / loadコマンド、restore label、offline verify、manifest contract、focused test | `neo4j.dump` / `system.dump`の生成、隔離volume load、countと代表3問のhash一致 | 静的検査済み。実機未検査 |

実機gateを通過していない項目は、T-FG-01 / T-FG-03の完了とは扱わない。

## 質問リスト

なし。Docker permissionとNeo4j実機結果は、Dockerが利用可能なWSL2環境で実行するgateの記録として扱う。

## スコープ外

- Docker daemonの起動、Neo4j imageの取得、実データのstart / stop / dump / load / verify。
- Compose、Neo4j schema、FastAPI、MCP、ChatGPT接続、UIの設計変更。
- 実credential、実backup、実ユーザーデータの作成、保存、送信。
- live volumeの削除、`down --volumes`、volume prune、既存dumpの上書き。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-OA-01 | T-FG-01 lifecycleのstatic contract test | 検査: `backend/tests/test_founder_graph_local_ops.py`が両helperのlifecycle marker、Composeのdurable volume、runbookのstop→start→persistence手順を検出する | 既知 |
| T-OA-02 | T-FG-03 backup / restoreのstatic contract test | 検査: 同testが両databaseのdump / load、隔離network、manifest count / hash、read-only query contractを検出する | 既知 |
| T-OA-03 | runbookとvalidatorの監査境界記録 | 検査: `scripts/founder-graph/validate_local_ops.py --root .`がPASSし、runbookがstatic PASSとlive未検査を分離して記載する | 既知 |
| T-OA-04 | syntaxと差分の検証 | 検査: `python -X utf8 -m py_compile scripts/founder-graph/verify_restore.py scripts/founder-graph/validate_local_ops.py`、`bash -n scripts/founder-graph/founder-graph.sh`、PowerShell parser、`git diff --check`が成功する | 類推可能 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 / 見直し条件 |
| --- | --- | --- | --- |
| ADR-OA-01 検査境界 | 既存helper、Compose、validator、focused testを静的に突き合わせる。Dockerを呼ばない | Docker未接続環境で実機結果を推測する案は、volume権限とdump / loadの実測を証明できないため却下 | static PASSを得ても実機gateは未完了として残す |
| ADR-OA-02 lifecycle evidence | runbookへ停止後の再起動と同一volume照合の観測手順を記載し、testで手順の存在を固定する | `start`とhealthだけを起動完了とする案は停止・永続化を検査できないため却下 | T-FG-01実機gateの観測項目が固定される |
| ADR-OA-03 restore evidence | `neo4j` / `system`、label、`--network none`、count、代表3問hashを一つのstatic contractとして維持する | node countだけをrestore成功とする案はrelationと内容の改変を検知できないため却下 | T-FG-03実機gateの最低証跡が固定される |

## ロールバック方針

- 追加したstatic testまたはrunbook記載だけを戻す場合、既存helperとComposeは変更しない。
- validatorが失敗した場合はDocker操作を開始せず、欠落した契約を計画へ戻して修正する。
- 実機gateが失敗した場合はlive volumeを削除せず、失敗した隔離volumeとscrub済み観測記録を保持する。

## 実装メモ

- 計画タスク: T-OA-01〜04
- 受け入れ条件: US-OA-01〜03
- エラー分類: static contract違反は入力修正が必要な検証エラー。Docker unavailableは実機gate未実行として記録する。
- API互換性: なし。helper、Compose、FastAPI、MCPの実行契約は変更しない。
- 外部通信: なし。
- ループ周回数: 1。既存のDocker-free validator、shell syntax、restore helperの入力契約を静的に照合した。
- 検査結果: `uv run --isolated --python 3.14 pytest backend/tests/test_founder_graph_local_ops.py -q` は23 passed / 2 skipped。`python scripts/founder-graph/validate_local_ops.py --root .`、`python -X utf8 -m py_compile scripts/founder-graph/verify_restore.py scripts/founder-graph/validate_local_ops.py`、`bash -n scripts/founder-graph/founder-graph.sh`、PowerShell parser、`git diff --check`は成功。Docker daemonが利用できないため実機gateは未実行。

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-09-22 | T-FG-01 / T-FG-03の静的監査、実機gate境界、lifecycle / restore evidenceのG/W/TとADRを定義 | Docker-free検査の証跡とNeo4j実機未検査を混同しないため | T-OA-01〜04 |
| 2026-09-22 | local ops validator、schema validator、shell syntaxの実行結果を追記 | static PASSと実機未実行を証跡上分離するため | T-OA-01〜04 |
| 2026-09-22 | lifecycle再起動・volume照合とdump / load / hashのstatic testを追加し、runbookへ実機gate手順と判定表を追加 | T-FG-01 / T-FG-03の不足していたDocker-free証跡を固定するため | T-OA-01〜04 |
