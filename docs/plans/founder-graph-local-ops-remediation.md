# Founder Graph local Neo4j operations remediation plan

最終検証日: 2026-09-22

## 位置づけと制約

本書は、Neo4j local ops の3巡目レビュー後に残った指摘を、実装前に再分解する補足計画である。製品要件とPhase順序の正本は [Founder Graphピボット計画](founder-graph-pivot.md) であり、本書はその T-FG-01（WSL2 / Docker Compose、health、start / stop）と T-FG-03（dump / load、世代管理、restore検証）だけを補強する。運用手順は [Founder Graph local runbook](../operations/founder-graph-local.md) と同期する。

- このturnの成果物は本計画書だけである。コード、既存test、Compose、runbookは変更しない。
- commit、branch、PR、Docker volumeの作成・削除はこのturnでは行わない。
- 既存の未コミット変更は利用者または別作業のものとして保持する。
- 各remediation sliceは単一目的、差分500行以内、レビュー30分以内を上限目安にする。Slice 3のDocker実機gateが未実施のまま実装を開始しない。
- 本書はリポジトリの [AGENTS.md](../../AGENTS.md) と [planning skill](../../skills/dev/planning/SKILL.md) のExit Criteriaに従う。

## 現在の実装状態

LO-R1、LO-R2、およびLO-R3のidentity/path契約は実装済みで、Dockerを使わない回帰検査は合格している。Docker daemonが利用できないため、SP-LO-03のUID/GID・mode・Neo4j dump/load実機gateだけは未完了であり、LO-R3全体を完了扱いにしない。

検証済みの境界は次のとおりである。

- `backend/tests/test_founder_graph_local_ops.py`: 21 passed、2 skipped。
- `python scripts/founder-graph/validate_local_ops.py --root .`: static PASS。
- `bash -n scripts/founder-graph/founder-graph.sh`: PASS。
- `migrate_schema.py --validate-only`: PASS。
- Docker start、health、backup、isolated restore、permission gate: Docker unavailable のため未検査。

## 要望 / ゴール / 成功指標

### 要望

3巡目レビューで確定したlocal-opsのHigh 2件とMedium 2件を、正のCypher契約、credential cleanup、exact identity判定、PowerShell/Bashのpath契約、Docker権限gateを含む1〜3個のbounded remediation sliceへ落とし込む。Docker daemonがない環境で未検査の権限仮説を合格扱いにしない。

### ゴール

manifest capture、restore verification、Bash helper、PowerShell helperが、live Neo4jのmutating query、credential残留、live volume誤認、相対restore pathを受け付けず、T-FG-01/T-FG-03を実機検証へ進められる計画を持つ。

### 成功指標

- `capture_manifest.py` と `verify_restore.py` が同じpositive read-query contractを使い、`CALL`、admin procedure、`USE`、semicolon、未許可top-level clauseを拒否する。
- 両方の `cypher-shell` invocationが `--access-mode read` を含み、credentialがargv、inspect、ログへ現れない。
- restart後のhealth失敗でも、Bashのtemporary auth fileが削除され、元の `FOUNDER_GRAPH_NEO4J_AUTH_FILE` が復元される。
- `foo-prod` を含むproject/source labelは受け入れ、exact live volume identity、`role=live`、`database`不一致だけを拒否する。
- PowerShell restore sourceの相対pathが、Docker呼出前にBash/runbookと同じ契約で拒否される。
- Docker実機gateで、mode 0700 backup bind mountとfresh restore volumeのUID 7474挙動を観測し、選択したpermission mechanismでbackup、isolated load、manifest verificationが成功する。gate未実施なら未完了とする。

## ベースラインと証跡

レビュー時点のlocal-ops baselineは10 tests passed、static validator PASS、Python/Bash syntax PASS、Compose YAML PASSである。Docker CLI/daemonはこの環境で利用できず、live start、backup dump、restore load、restore verificationは未検査である。

| 検査 | baseline | このturnで確認した境界 |
| --- | --- | --- |
| `backend/tests/test_founder_graph_local_ops.py` | 10 passed | 現在のsystem Pythonにはpytestがなく、再実行はしていない。既知baselineを計画の前提として記録する |
| `python scripts/founder-graph/validate_local_ops.py --root .` | PASS (static, Docker-free) | PASS |
| `python -m py_compile scripts/founder-graph/capture_manifest.py scripts/founder-graph/verify_restore.py scripts/founder-graph/validate_local_ops.py` | PASS | PASS |
| `bash -n scripts/founder-graph/founder-graph.sh` | PASS | PASS |
| Compose YAML parse | PASS | system PythonにPyYAMLがなく、baseline結果を記録。`uv run`環境で再確認する |
| Docker CLI / daemon | unavailable | Docker実機gateを実行していない |

Baselineの10件は次の既存testで構成される: `test_daemon_free_contract_validator_passes`、`test_compose_uses_loopback_ports_durable_volume_and_namespaced_network`、`test_compose_healthcheck_uses_readonly_secret_file`、`test_helpers_are_non_destructive_and_use_secret_file_health_and_capture`、`test_powershell_dispatches_restore_verification_and_manifest_capture`、`test_restore_manifest_live_alias_labels_and_whitespace_contract`、`test_restore_verifier_requires_exact_labels_and_manifest_metadata`、`test_restore_verifier_static_contract_has_safe_secret_argv`、`test_manifest_capture_query_contract_is_docker_free`、`test_runbook_documents_local_ports_secrets_persistence_capture_and_drill`。

## 確定findingsと対応境界

| ID / severity | 現在の不備 | 影響 | 対応slice |
| --- | --- | --- | --- |
| LO-H1 / High | `capture_manifest.py` と `verify_restore.py` のmutating keyword blacklistが `CALL db.createLabel` のようなwrite procedureを通し、`QUERY_SHELL`も `cypher-shell --access-mode read`を指定しない | queries JSONまたはmanifestを編集できる利用者が、capture対象またはrestore verification対象のDBへwrite/admin操作を渡せる | LO-R1 |
| LO-H2 / High | Bash `EXIT` trapのrestart branch内で `wait_for_healthy` が `fail` / `exit`すると、後続の `cleanup_auth_secret` に到達しない | temporary credential fileが残り、元のauth-file環境変数も復元されない | LO-R2 |
| LO-M1 / Medium | verifierが全label key/valueへlive-alias regexを適用する | 正当な `project=foo-prod`、`source=/safe/foo-prod/...`、非identity labelがfalse rejectされる | LO-R3 |
| LO-M2 / Medium | PowerShell `Assert-RestoreSource` が `IsPathRooted` を確認せず、Bash/runbookのabsolute path契約と不一致 | 実行環境差で相対pathをrestore sourceとして受け付ける | LO-R3 |
| LO-U1 / unknown | mode 0700 backup bind mountをUID 7474が書けない可能性 | backup dumpがpermission errorで止まる可能性 | SP-LO-03 → LO-R3 |
| LO-U2 / unknown | fresh named volumeへ `--user neo4j` でloadすると、entrypointのchownを経ず書込失敗する可能性 | isolated restoreがload failureになる可能性 | SP-LO-03 → LO-R3 |

## ユーザーストーリーと受け入れ条件

### US-LO-01 Query safety contract

As a local-ops maintainer, I want capture and restore verification to accept only a positive read-query contract, so that an editable manifest cannot mutate or administer Neo4j.

Given: a query is passed to manifest capture or restore verification.

When: the shared query validator examines the complete token stream and the command builds `cypher-shell` argv.

Then: a single `MATCH` or `OPTIONAL MATCH` read statement with `WHERE` / `WITH`, `RETURN`, and optional `ORDER BY` / `SKIP` / `LIMIT` clauses passes; `CALL`, `db.*` or `dbms.*` procedure invocation, admin clauses, `USE`, semicolon, comments, multiple statements, and any top-level clause outside that set are rejected; `cypher-shell` includes `--access-mode read`.

### US-LO-02 Credential cleanup on restart failure

As a local-ops operator, I want the Bash EXIT path to clean temporary credentials before reporting a restart failure, so that a failed health check cannot leave a secret on disk.

Given: an action has created a mode-0600 temporary auth file, `RESTART_REQUIRED=1`, and the restart health loop never reaches `healthy`.

When: the EXIT trap handles the non-zero action status.

Then: the trap is removed before recovery commands, the health failure is returned rather than exiting from inside the trap, cleanup runs exactly once, the temporary file is absent, a pre-existing `FOUNDER_GRAPH_NEO4J_AUTH_FILE` value is restored, and the process exits non-zero without printing the credential.

### US-LO-03 Exact restore identity

As a restore operator, I want live-volume protection to inspect only volume identity and required role/database labels, so that project and source metadata remain usable when they contain `prod` text.

Given: a new restore volume has an allowed restore name, `com.openai.founder_graph.role=restore`, `com.openai.founder_graph.database=neo4j`, `project=foo-prod`, and `source=/safe/foo-prod/run`; an unrelated label key/value also contains `live` or `prod`.

When: the verifier checks the volume and labels against the manifest.

Then: the volume passes when its name is not an exact configured live alias and the required labels match; exact configured live names, `role=live`, or a database value other than `neo4j` fail; project, source, and unrelated labels are compared only by their explicit contract and do not invoke live-alias regex.

### US-LO-04 Cross-shell restore path contract

As a PowerShell operator, I want restore source validation to match Bash and the runbook, so that path interpretation cannot vary by shell.

Given: a relative directory contains regular `neo4j.dump` and `system.dump` files, and an equivalent absolute directory is available.

When: PowerShell `restore` validates the source before any Docker command.

Then: the relative path is rejected with the absolute-path contract error before Docker is called; the absolute path proceeds to the existing non-symlink, repository/data exclusion, and dump-file checks.

### US-LO-05 Permission-gated backup and restore

As a local-only Founder Graph operator, I want backup and isolated restore permissions proven against the pinned Neo4j image, so that static checks are not mistaken for a working drill.

Given: WSL2 Docker is available, `neo4j:5.26-community` is already present, a synthetic fixture is loaded, the backup directory is mode 0700, and a fresh labeled restore volume is used.

When: the Docker gate runs backup, both database loads, health, and manifest verification with `--network none` for restore operations.

Then: backup dumps are written without granting broad read/write access, both databases load using the observed supported ownership strategy, counts and three result hashes match, the live volume is untouched, and the gate records command exit codes, UID/GID, modes, and scrubbed logs; an unresolved permission failure keeps LO-R3 incomplete and returns the work to planning.

## 回帰テストのRED基準

The following exact pytest node names are implementation-entry tests. Each listed RED test must fail against the current implementation before its slice is coded, then pass with the same node after the slice. No test is added in this planning-only turn.

### LO-R1 RED tests

- `backend/tests/test_founder_graph_local_ops.py::test_manifest_query_contract_rejects_call_admin_use_and_semicolon`
- `backend/tests/test_founder_graph_local_ops.py::test_restore_manifest_query_contract_rejects_call_admin_use_and_semicolon`
- `backend/tests/test_founder_graph_local_ops.py::test_manifest_query_contract_rejects_comments_and_multiple_statements`
- `backend/tests/test_founder_graph_local_ops.py::test_restore_manifest_query_contract_rejects_comments_and_multiple_statements`
- `backend/tests/test_founder_graph_local_ops.py::test_manifest_and_restore_query_shell_force_cypher_read_access_mode`

### LO-R2 RED tests

- `backend/tests/test_founder_graph_local_ops.py::test_bash_exit_trap_cleans_auth_secret_when_restart_health_fails`
- `backend/tests/test_founder_graph_local_ops.py::test_bash_exit_trap_restores_preexisting_auth_file_when_restart_health_fails`

### LO-R3 RED tests

- `backend/tests/test_founder_graph_local_ops.py::test_restore_verifier_accepts_prod_tokens_in_project_and_source_labels`
- `backend/tests/test_founder_graph_local_ops.py::test_restore_verifier_ignores_alias_tokens_in_unrelated_labels`
- `backend/tests/test_founder_graph_local_ops.py::test_restore_volume_name_accepts_non_live_prod_suffix`
- `backend/tests/test_founder_graph_local_ops.py::test_powershell_restore_source_requires_absolute_path`

### Regression tests retained or extended

- `test_restore_verifier_requires_exact_labels_and_manifest_metadata` continues to reject exact role/database mismatches and accepts exact expected project/source matches.
- `test_restore_manifest_live_alias_labels_and_whitespace_contract` is updated only to preserve exact live aliases and newline/hash behavior; its unrelated-label case must not reintroduce the broad scan.
- `test_helpers_are_non_destructive_and_use_secret_file_health_and_capture` gains assertions for the read mode, cleanup ordering, exact alias policy, and PowerShell rooted-path check.

## Bounded remediation slices

### LO-R1 — Positive Cypher contract and read mode

**Purpose:** close LO-H1 without expanding query capability.

**Implementation boundary:** introduce one shared query-contract implementation for `capture_manifest.py` and `verify_restore.py`, or keep the two adapters mechanically identical if the import boundary prevents a shared module. The contract must tokenize one statement, reject comments and semicolon delimiters, permit only the manifest read clause sequence, and reject `CALL`, `USE`, admin clauses, write clauses, and unknown top-level clauses. Update both shell snippets to pass `cypher-shell --access-mode read`. Update the static validator and the local-ops test contract for the new security tokens. Update the local runbook to show the positive query shape and read mode.

**Files owned by this slice:** `scripts/founder-graph/capture_manifest.py`, `scripts/founder-graph/verify_restore.py`, `scripts/founder-graph/validate_local_ops.py`, `backend/tests/test_founder_graph_local_ops.py`, `docs/operations/founder-graph-local.md`.

**Completion判定（検査:）** `uv run pytest backend/tests/test_founder_graph_local_ops.py -q` passes the LO-R1 RED tests and all baseline tests; `python -X utf8 -m py_compile scripts/founder-graph/capture_manifest.py scripts/founder-graph/verify_restore.py scripts/founder-graph/validate_local_ops.py`; static source inspection confirms `--access-mode read` in both shells and no password argv; `git diff --check` passes; the slice diff is at most 500 lines.

**不確実性:** 類推可能. The required read clauses are already represented by the three manifest fixtures; parser edge cases are bounded by rejection rather than new Cypher support.

### LO-R2 — Non-recursive Bash EXIT cleanup

**Purpose:** close LO-H2 while preserving restart-before-exit behavior.

**Implementation boundary:** change `wait_for_healthy` to report failure without calling `exit` from the EXIT trap; remove the EXIT trap before restart recovery; capture the original status, attempt restart, set a failure status on restart/health failure, run `cleanup_auth_secret` unconditionally, and exit only after cleanup. Preserve mode 0600 creation, environment restoration, non-destructive volume policy, and scrubbed errors. Add a temporary fake-Docker test harness that proves the failing-health branch and pre-existing env restoration without a real daemon.

**Files owned by this slice:** `scripts/founder-graph/founder-graph.sh`, `backend/tests/test_founder_graph_local_ops.py`, `docs/operations/founder-graph-local.md`.

**Completion判定（検査:）** the two LO-R2 RED tests pass; `bash -n scripts/founder-graph/founder-graph.sh` passes; the helper test proves a non-zero exit, no `founder-graph-auth.*` file under the test `TMPDIR`, restored prior auth-file variable, no recursive trap, and no credential in stdout/stderr; `git diff --check` passes; the slice diff is at most 500 lines.

**不確実性:** 類推可能. The failure path is local shell control flow and does not require Docker.

### SP-LO-03 — Docker permissions spike before LO-R3

**Purpose:** determine the safe, supported permission mechanism for LO-U1 and LO-U2 before implementation changes.

**Timebox and precondition:** one 30-minute run on WSL2 with Docker daemon available and `neo4j:5.26-community` already present. Do not pull an image, use real data, or use a real credential. If the precondition is absent, record `Docker unavailable` and do not create an implementation patch.

**Observation protocol:**

1. Create a synthetic graph and a test-only backup directory with owner-only mode 0700. Record host UID/GID and directory mode.
2. Run the pinned image as UID/GID 7474 against the bind mount with a write probe, then run the current `database dump` path. Record exit code, effective UID/GID, output ownership, and mode.
3. Create a fresh test-only restore volume with exact `role=restore` and `database=neo4j` labels. Run the current `--user neo4j` load for `neo4j` and `system`; record whether the data directory is writable and whether entrypoint ownership initialization is bypassed.
4. Run isolated verification with `--network none`; compare node count, relationship count, and the three manifest hashes. Inspect command metadata and logs for credential exposure after redaction.

**Decision rule:** retain owner-only or explicit single-UID access for backup data. Select an ownership initialization or staging mechanism only when the observed command succeeds, keeps restore offline, leaves the live volume untouched, and does not place a credential in argv, inspect, or logs. A broad `chmod`, global volume reuse, `down --volumes`, volume prune, or blind removal of `--user neo4j` is not an accepted workaround.

**Spike deliverable and completion判定（検査:）** a scrubbed observation record containing image digest or pinned tag, commands, exit codes, UID/GID, modes, failure text, and the selected or rejected mechanism; no repository file is required for the spike. The spike is `未知` until the gate runs.

### LO-R3 — Exact identity, absolute PowerShell path, and live Docker gate

**Purpose:** close LO-M1 and LO-M2, then apply only the permission strategy proven by SP-LO-03.

**Implementation boundary:** limit live-alias protection to exact configured live volume names and an exact reserved restore name if retained by the contract. Require `role=restore` and `database=neo4j` by exact key/value. Compare `expected_project` and `expected_source` only with their explicit equality checks; never run the live-alias regex across arbitrary label keys or values. Align Bash and PowerShell volume validation with the same exact-name table. Add `[System.IO.Path]::IsPathRooted()` to PowerShell `Assert-RestoreSource` before filesystem access. Update the runbook with the exact identity table, absolute-path rule, and the Docker gate result. Apply the SP-LO-03 permission mechanism to backup/load only after its evidence is green.

**Files owned by this slice:** `scripts/founder-graph/verify_restore.py`, `scripts/founder-graph/founder-graph.sh`, `scripts/founder-graph/founder-graph.ps1`, `scripts/founder-graph/validate_local_ops.py`, `backend/tests/test_founder_graph_local_ops.py`, `docs/operations/founder-graph-local.md`.

**Completion判定（検査:）** the four LO-R3 RED tests and retained exact-label regression tests pass; PowerShell parser/syntax validation passes; static validator, Python syntax, Bash syntax, Compose YAML validation, and `git diff --check` pass; SP-LO-03 is green with backup, both loads, and offline verification; the slice diff is at most 500 lines. If the gate remains unavailable or fails, LO-R3 is not complete and the issue returns to planning with the scrubbed evidence.

**不確実性:** 未知 before SP-LO-03; 類推可能 for the label/path contract after the spike. No implementation task starts while the unknown permission result is unresolved.

Slice order is LO-R1 → LO-R2 → SP-LO-03 → LO-R3. Only one slice may be active at a time. A failing slice blocks the next slice; no unrelated UI, kernel, MCP, or schema work is bundled.

## Credential and permissions threat model

| Asset / boundary | Threat | Control required by this plan | Evidence |
| --- | --- | --- | --- |
| Live and restore Neo4j data | Manifest query invokes a write procedure or admin operation | Positive clause contract plus `--access-mode read`; reject `CALL`, `USE`, semicolon, comments, multiple statements, and unknown clauses | LO-R1 RED tests, source inspection, offline restore verification |
| `FOUNDER_GRAPH_NEO4J_AUTH` and temporary secret file | EXIT trap exits during health recovery before cleanup | Disable trap before recovery, make health check return, cleanup unconditionally, restore prior env value | LO-R2 subprocess tests and file absence check |
| Backup dumps and host bind mount | UID 7474 cannot write mode 0700 directory, or broad permission change exposes data | Docker spike observes effective UID/GID; accepted fix preserves owner-only or explicit single-UID access; no broad chmod | SP-LO-03 record and live gate |
| Fresh restore volume | `--user neo4j` bypasses ownership initialization and load fails, or a workaround targets live data | Use a fresh labeled volume, prove ownership before load, keep `--network none`, retain failed isolated volume for diagnosis | SP-LO-03 and LO-R3 gate |
| Volume identity and labels | Alias regex blocks valid metadata or allows a live target | Exact configured live names plus exact `role=restore` and `database=neo4j`; ignore unrelated label text | LO-R3 tests with `foo-prod`, exact live names, role/database mismatch |
| PowerShell source path | Relative path or reparse path is interpreted differently from Bash | Require rooted path before `Get-Item`; retain regular non-symlink, repository/data exclusion, and dump checks | PowerShell test and runbook comparison |

Residual risk: the local operator controls the host and can bypass helper policy outside this runbook. This plan reduces accidental and manifest-driven mutation; it does not claim host-level containment or protect credentials deliberately copied by the operator.

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| Q-LO-01 | 追加の製品要件判断はない。Docker permission mechanismはSP-LO-03の観測結果で技術責任者が選び、未解決ならLO-R3を停止する | 技術責任者 | LO-R3開始前 |

## スコープ外

- Neo4j schema、migration、FastAPI、MCP transport、ChatGPT接続、UI、model catalog、外部service。
- 任意Cypherの一般公開、read modeの解除、write procedureの許可、外部networkの追加。
- 実credential、実ユーザーデータ、実backup dumpのリポジトリ保存。
- live volumeの削除、`down --volumes`、volume prune、既存Postgresの廃止。
- Docker daemonがない環境での権限結果の推測、広いchmodによる暫定通過、失敗したrestore volumeの無検証再利用。
- このturnでのコード、既存test、Compose、runbook編集、commit、PR、handoff event。

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 / 見直し条件 |
| --- | --- | --- | --- |
| ADR-LO-01 Query safety | captureとverifyが同じpositive read-query contractを使い、`cypher-shell --access-mode read`を強制する。manifest用途に必要なread clauseだけを許可する | keyword blacklistだけではprocedure、admin clause、statement stackingを表現できず、任意Cypherは用途境界を越えるため却下 | 有効な3 query fixtureは維持し、未許可queryは実行前に拒否する。query fixtureを増やすときはcontractとRED testを先に更新する |
| ADR-LO-02 EXIT cleanup | EXIT trapを非再帰にし、trap解除、restart attempt、status更新、secret cleanup、exitの順序を固定する | trap内の`fail` / `exit`はcleanupを迂回し、credential残留を起こすため却下 | restart failureは非zeroで報告されるが、cleanupは必ず完了する |
| ADR-LO-03 Restore identity | live protectionはexact volume nameとrequired `role` / `database` identityに限定し、project/sourceはexact equalityだけで検査する | 全label key/valueへのlive/prod regexは`foo-prod`をfalse rejectし、metadataの意味を変えるため却下 | exact live aliasは拒否し、正当なproject/source labelは受け入れる。新しいlive aliasは明示的なidentity tableへ追加する |
| ADR-LO-04 Permission mechanism | Docker実機でUID/GID、mode、entrypoint ownership、dump/load exitを観測してから、owner-onlyまたは明示single-UIDの手段を選ぶ | Dockerなしでchmod、root、`--user`削除を決めるとdata exposureまたはrestore failureを見逃すため却下 | SP-LO-03のevidenceがない限りLO-R3を完了扱いにしない |
| ADR-LO-05 Shell path parity | Bash、PowerShell、runbookでrestore sourceをabsolute pathとし、PowerShellもrooted-path checkを行う | shellごとにrelative pathを許可すると同じbackupの解釈が変わり、操作ミスを再現できないため却下 | relative sourceはDocker前に拒否される |

## ロールバック方針

- LO-R1、LO-R2、LO-R3は独立PRに分け、各PRは自身のcommitだけをrevertできるようにする。このplanning turnではcommitを作らない。
- LO-R1のrollback時はcapture-manifestとverify-restoreを再開せず、旧blacklistへ戻った状態を安全なread contractとみなさない。untrusted queryを受ける操作を停止し、修正PRを再計画する。
- LO-R2のrollback時はBashのDocker actionsを停止し、credential rotateとtemp-file auditを行う。既存volumeやdumpを削除しない。
- LO-R3のlabel/path rollback時はrestore verificationを停止し、exact identityとabsolute pathの整合が戻るまで新規restoreを作らない。
- SP-LO-03/LO-R3でpermission failureが出た場合、test-only restore volumeとdumpを原因調査用に保持し、live volumeへfallbackしない。再実行は明示したtest targetだけを使い、既存volumeへの破壊操作を実行しない。
- 全rollbackでcredentialをログ、argv、Gitへ書かず、変更前のJSON manifest、既存DB、既存Postgresを物理削除しない。

## Exit Criteria

- 全US-LO-01〜US-LO-05に `Given:`、`When:`、`Then:` があり、各Thenが観測可能である。
- LO-R1〜LO-R3の各RED testが実装前にred、実装後に同じpytest nodeでgreenになり、既存10 testsもgreenである。
- `uv run pytest backend/tests/test_founder_graph_local_ops.py -q` が0 failedになる。
- `python -X utf8 -m py_compile scripts/founder-graph/capture_manifest.py scripts/founder-graph/verify_restore.py scripts/founder-graph/validate_local_ops.py`、`bash -n scripts/founder-graph/founder-graph.sh`、PowerShell parser check、Compose YAML parseがgreenになる。
- `python scripts/founder-graph/validate_local_ops.py --root .` がPASSになり、validatorがpositive query contract、read mode、cleanup、exact identity、absolute pathの必須tokenを検査する。
- `git diff --check` がgreenで、相対Markdown link（本書、pivot、runbook、AGENTS、planning skill）が解決する。
- planning skillが定める禁止曖昧語のscanが0件である。
- 各sliceの実装diffが500行以内で、既存未関係変更を含まない。
- Docker実機gateが、pinned image、synthetic fixture、mode 0700 backup、fresh labeled restore volume、offline verification、credential非露出、live volume非変更を記録してPASSになる。Docker unavailableまたはpermission未解決は完了条件未達として明示される。
- T-FG-01/T-FG-03のstart、health、backup、load、verifyの結果をrunbookへ反映し、static PASSだけをlive PASSと報告しない。

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-09-22 | 3巡目レビューのHigh 2件、Medium 2件、Docker権限の未知2件を、LO-R1〜LO-R3とSP-LO-03へ再分解。positive query contract、read mode、non-recursive cleanup、exact identity、PowerShell absolute path、Docker gate、threat model、rollback、Exit Criteriaを追加 | blacklist、credential cleanup、label false reject、shell path divergenceを実装前の検証可能な契約へ固定し、Docker未検査の仮説を完了扱いにしないため | LO-R1、LO-R2、SP-LO-03、LO-R3 |
