# Founder Graph kernel remediation plan

最終検証日: 2026-09-22

## 位置づけと現状

本書は、3回の実装・レビュー反復後に計画へ差し戻したGraph kernelの残課題だけを再分解する補足計画である。製品要件、8章の章名、Phase順序、全体ADRは[Founder Graphピボット計画](founder-graph-pivot.md)を正本とし、本書はそれを置き換えない。

- 対象実装: [founder_graph.py](../../backend/dots/founder_graph.py) と [test_founder_graph.py](../../backend/tests/test_founder_graph.py)。現在のkernelはpartialであり、既存のowner必須、終端Run、typed relation、8章の基本shape、typed authorization snapshot、基本ReportVersionは実装済みである。
- R1〜R3のfocused kernel suiteは51 passed。全backend suiteは、直近の統合検査で0 failed（環境依存skipを除く）まで回復している。local-opsの残件は別計画に分離し、Docker実機gate未実施は完了根拠に含めない。
- 下記の回帰テスト名は、現実装でredになることを確認してから各sliceへ追加する。各sliceは500行以内を上限目安とし、共通moduleを順番に更新するが、契約責務とテスト所有範囲は重複させない。

## 実装状況

FG-R1、FG-R2、FG-R3はコード契約と回帰テストを完了した。`NodeType.SOURCE` を追加したため、read serviceのfield allowlistにもSource / SourceRevisionと`egress_policy`を反映し、canonical Sourceがshareable read viewへ到達できることを追加検査している。Neo4jへのmigration・永続adapterと既存DBデータ移行は後続タスクであり、本計画の完了条件には含めない。

## 要望 / ゴール / 成功指標

### 要望

3回のレビューで残った許諾snapshot、章内参照、provenance、read projection、Source履歴の境界を、実装者が再解釈せず検査できる小さな契約へ分解する。

### ゴール

現行Campaignだけを外部投影とRunへ認可し、全ReportSectionの参照とownerを検証し、生成対象を追跡可能にし、read MCPで使う全ノードを明示allowlistで投影し、SourceとSourceRevisionの訂正履歴を不変に保持する。

### 成功指標

- 旧authorization snapshotを使うRun検証とexplicit projectionが0件通過する。
- section内のClaim / Evidence参照について、存在不明、別owner、Claimとの不一致が0件通過する。
- `GENERATED` provenanceのtarget、source、model、prompt/rule、時刻、idempotency keyが100%存在する。
- final ReportVersionが8章、章別Claim、章別Evidence、Run、財務式、DecisionCriterionをすべて満たす。
- read-MCP対象の各NodeTypeにprojection allowlistがあり、private/local-only fieldの外部返却が0件である。
- SourceRevisionを追加・訂正しても旧revisionのcontent、hash、provenanceが変化せず、current pointerだけが一意に進む。

## 実装前レビュー指摘（履歴）

| 領域 | 現在の不備 | この計画で閉じるテスト |
| --- | --- | --- |
| authorization supersession | `is_active()`が期限だけを見て、`validate_run_campaign_reference()`がCampaignの現行snapshot ID/revisionを比較しない。旧snapshotでRunとexplicit projectionが通る。 | `test_validate_run_campaign_reference_rejects_superseded_snapshot`、`test_explicit_projection_rejects_superseded_authorization_snapshot` |
| section integrity | `validate_report_references()`がReport直下のIDだけを検査し、Sectionのclaim/evidence IDの存在・owner・Claim対応を検査しない。 | `test_validate_report_references_rejects_cross_owner_section_claim_and_evidence`、`test_validate_claim_evidence_references_requires_evidence_claim_identity` |
| generated target | `Provenance(origin=GENERATED, ...)`がtarget_idなしで生成できる。 | `test_generated_provenance_requires_target_id` |
| final report contracts | 8章の非空shapeとReport直下IDだけでfinal化でき、章別参照、財務式、DecisionCriterionを強制しない。 | `test_final_report_requires_section_claim_and_evidence_contract`、`test_final_report_requires_financial_formulas_and_decision_criteria` |
| safe projections | `project_shareable()`がPerson、Asset、ResearchMaterial以外を空dictにし、remaining read-MCP nodeを返せない。任意mapping、raw snapshot、private fieldのallowlistも不足する。 | `test_shareable_projection_covers_all_read_mcp_node_types_without_private_fields`、`test_local_only_and_explicit_projection_fail_closed_for_all_read_mcp_node_types` |
| Source history | Source本体、revision番号、current pointer、supersedes、owner整合性がなく、`source_id`は文字列参照だけである。 | `test_source_revision_history_requires_current_source_and_monotonic_revision`、`test_source_revision_supersession_preserves_prior_revision`、`test_source_revision_history_rejects_cross_owner_orphan_revision` |

## ユーザーストーリーと受け入れ条件

### US-R1 認可と履歴の境界

As a GraphWriteService maintainer, I want every Run and explicit projection to use the current Campaign authorization snapshot, so that a scope change cannot reuse an old external-egress permission.

Given: approved Campaignのscopeを変更して新revisionを再承認し、旧snapshot、旧Run、旧provenanceを保持する。

When: 旧snapshotを渡したRun検証またはexplicit projectionを実行する。

Then: 旧snapshotはsupersededとして拒否され、現行ID・revision・owner・expiryが一致するsnapshotだけが通過し、`GENERATED` provenanceはtarget_idを含む。

### US-R2 レポートの章内整合性

As a report writer, I want each ReportSection reference to resolve to same-owner typed Claims and Evidence, so that a final report cannot cite another owner or an unrelated claim.

Given: 8個のSectionにClaim/Evidence ID、Run、financial_formulas、decision_criteriaを設定し、一部のIDを不存在または別ownerへ置き換える。

When: draftまたはfinalのReportVersionをreference validatorへ渡す。

Then: draftはshapeを保持し、invalid referenceを拒否し、finalは全8章の章別Claim・Evidence・Run・financial_formulas・decision_criteriaを満たした場合だけ生成される。

### US-R3 安全なread projectionとSource履歴

As a read-MCP consumer, I want every supported node to have an explicit safe projection and every source correction to retain its prior revision, so that search/fetch returns useful typed data without private leakage or history loss.

Given: read-MCP対象の各NodeTypeにlocal_only、shareable、explicitのfixtureとSourceのrevision chainを用意する。

When: projectionまたはSourceRevision history validatorを実行する。

Then: allowlisted shareable fieldsだけが返り、local_onlyと無効なexplicit snapshotは空または拒否となり、Sourceのcurrent revisionは一意で旧revisionは不変のまま残る。

## 回帰テストの赤基準

各テストは実装前に現行コードで失敗することを記録し、実装後に同じpytest nodeでgreenを確認する。既存の24件を置き換えず、残存契約を追加する。

### R1: authorization / provenance

- `backend/tests/test_founder_graph.py::test_validate_run_campaign_reference_rejects_superseded_snapshot`
- `backend/tests/test_founder_graph.py::test_explicit_projection_rejects_superseded_authorization_snapshot`
- `backend/tests/test_founder_graph.py::test_generated_provenance_requires_target_id`

### R2: section references / final contract

- `backend/tests/test_founder_graph.py::test_validate_report_references_rejects_cross_owner_section_claim_and_evidence`
- `backend/tests/test_founder_graph.py::test_validate_claim_evidence_references_requires_evidence_claim_identity`
- `backend/tests/test_founder_graph.py::test_final_report_requires_section_claim_and_evidence_contract`
- `backend/tests/test_founder_graph.py::test_final_report_requires_financial_formulas_and_decision_criteria`

### R3: projections / Source history

- `backend/tests/test_founder_graph.py::test_shareable_projection_covers_all_read_mcp_node_types_without_private_fields`
- `backend/tests/test_founder_graph.py::test_local_only_and_explicit_projection_fail_closed_for_all_read_mcp_node_types`
- `backend/tests/test_founder_graph.py::test_source_revision_history_requires_current_source_and_monotonic_revision`
- `backend/tests/test_founder_graph.py::test_source_revision_supersession_preserves_prior_revision`
- `backend/tests/test_founder_graph.py::test_source_revision_history_rejects_cross_owner_orphan_revision`

## 実装タスク

| ID | bounded implementation slice | 成果物と完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| FG-R1 | authorization snapshot supersession と generated target provenance | `ResearchCampaign`の現行snapshot ID/revision/owner/expiryをRunとexplicit projectionの共通検証へ通し、scope変更時に旧snapshotをsupersededとして扱う。`GENERATED` provenanceのtarget/source/model/prompt-or-ruleを必須化する。検査: R1の3回帰テスト、既存 `uv run pytest backend/tests/test_founder_graph.py -q`、`python -X utf8 -m py_compile backend/dots/founder_graph.py`。 | 類推可能 |
| FG-R2 | section-level owner/reference integrity と final report contracts | `validate_report_references()`へClaimsを渡し、各Sectionのclaim/evidence ID、owner、Evidence→Claim identityを検証する。draft/finalを分け、finalだけ全章のtyped reference、Run、Evidence、財務式、DecisionCriterionを必須化する。検査: R2の4回帰テスト、既存section title/order tests、focused kernel suite。 | 類推可能 |
| FG-R3 | safe projections と Source/SourceRevision history | `Source`をSourceRevisionから分離し、revision番号、current_revision_id、supersedes_id、owner、hash、statusを追加する。Source history validatorと、`OWNER_PROFILE`、`IDEA`、`ASSET`、`PERSON`、`ORGANIZATION`、`SOURCE`、`SOURCE_REVISION`、legacy `RESEARCH_MATERIAL`、`CLAIM`、`EVIDENCE`、`RESEARCH_CAMPAIGN`、`RESEARCH_RUN`、`REPORT_VERSION`、`REPORT_SECTION`、`DECISION`、`EXPERIMENT`、`INSTRUCTION_ARTIFACT`の全NodeTypeに対する明示allowlist projectionを実装する。`REPORT_SECTION`はReportVersionのnested childとしても安全なprojectionを持ち、private raw fieldsを返さない。検査: R3の5回帰テスト、projection allowlistの全NodeType parameterization、focused kernel suite、`git diff --check`。 | 類推可能 |

### FG-R3 実装境界

- canonical `Source` は論理原本の owner、タイトル、kind、locator、egress policy、current revision pointer、statusを保持し、content本文は `SourceRevision` にだけ保持する。
- `SourceRevision` は source ID、正の revision 番号、content hash、取得時刻、supersedes ID、status、provenanceを不変値として保持する。revision chain は同一 owner・同一 source、単調増加、直前 revision の supersedes を要求し、旧 revision の content/hash/provenance は変更しない。
- `validate_source_revision_history(source, revisions)` は current pointer が一意に解決し、chain に orphan、cross-owner、重複番号、逆順 supersedes がない場合だけ成功する。空の revision 集合、current pointer 不一致、source ID/owner 不一致は拒否する。
- `project_shareable()` は NodeType ごとの静的 allowlist を経由し、`owner_id`、`provenance`、raw mapping、private contact/notes、local-only content を返さない。`REPORT_SECTION` は scalar ID、title/content、typed reference IDsだけを返す。未対応型、local-only、期限切れまたは不一致の explicit authorization は fail-closed にする。

各sliceの実装PRは、上表のファイル範囲だけを変更し、差分500行以内を維持する。FG-R1からFG-R3は同じdomain moduleを触るため、順番はR1→R2→R3とし、前sliceのgreenを次sliceの開始条件にする。

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| Q-R0 | 追加決定なし。既存のFounder Graph正本、local-only初期値、8章契約を適用する。 | 利用者兼製品責任者 | 2026-09-21 |

## スコープ外

- Neo4j schema、FastAPI、MCP transport、ChatGPT接続、UI、永続repositoryの変更。
- 任意Cypher、物理削除、外部AI呼び出し、モデルcatalogの変更。
- [founder_graph_attachments.py](../../backend/dots/founder_graph_attachments.py) の修正。Attachment storeは別レビューで扱い、kernel sliceの受入条件へ混ぜない。
- [founder-graph-local.md](../operations/founder-graph-local.md)、Compose、Bash、PowerShell、restore verifierの修正。local-opsの4失敗は別ownerの修正対象である。
- Source履歴を既存DBへ移すmigration。実DBは未接続であり、value-object契約を先に確定する。

## 関係しない一時的失敗の扱い

| 領域 | 現在の観測 | 扱い |
| --- | --- | --- |
| Attachment | `backend/tests/test_founder_graph_attachments.py`は13 passed、1 skipped。過去のcollection時のmodule欠落は、ファイル追加前の一時状態だった。 | Graph kernelのR1〜R3から除外する。Windowsのsymlink skipは環境制約として記録し、Attachment ownerの再レビューで閉じる。 |
| local-ops | `test_daemon_free_contract_validator_passes`、`test_compose_healthcheck_and_secret_contract`、`test_helpers_are_local_and_non_destructive`、`test_restore_verifier_manifest_and_docker_fail_closed`が、secret-file移行後のvalidator/test契約不一致で失敗している。 | kernel sliceでは修正しない。local-ops ownerがCompose、helper、validator、manifest、secret-fileの契約を同じ変更で同期し、全backend gateの前にgreenへ戻す。 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| ADR-R1 現行authorization | explicit projectionはbare boolまたは期限だけのsnapshotを信用せず、Campaignのcurrent snapshot ID/revision/owner/expiryを検証する。scope変更は同一Campaign内の不変revision chainとして保存する。 | `is_active()`だけで許可する案は旧scopeの外部送信を止められないため却下。 | 旧Runと旧projectionは監査に残るが、現行外部投影から除外される。 |
| ADR-R2 章内参照 | Sectionはtyped Claim/Evidence IDを持ち、validatorが存在・owner・Claim対応を確認する。finalだけ財務式とDecisionCriterionを必須化する。 | 8個の空でない文字列だけをfinalとする案は根拠と判断条件を検証できないため却下。 | draftの編集余地を保ちつつ、finalの受入境界を固定する。 |
| ADR-R3 Sourceとprojection | Sourceを論理原本、SourceRevisionを不変版として分離し、read projectionは全NodeTypeごとの静的allowlistで構成する。`REPORT_SECTION`もnested safe projectionを持つ。 | `ResearchMaterial`をSourceの別名として維持する案はcurrent revisionとsupersedesを表せず、dataclass全field返却もprivate leakageを招くため却下。 | legacy `ResearchMaterial`はadapter用途で保持し、canonical Source historyと外部projectionを二重正本にしない。 |

## ロールバック

- 各sliceを独立commit/PRとして適用し、失敗時はそのsliceのcommitだけをrevertする。既存Run、ReportVersion、SourceRevisionを物理削除しない。
- R1のprojection引数変更はMCP接続前に行う。rollback時は旧APIを一時復元し、外部接続を再開する前にcurrent-snapshot検証を再確認する。
- R2のfinal強化で既存fixtureがinvalidになった場合、fixtureをdraftへ戻すか不足fieldを補う。履歴を削除して通過させない。
- R3のSource分離はvalue-objectとvalidatorだけに留め、DB migrationを開始しない。旧`ResearchMaterial` importは保持し、変換失敗時はlegacy read-onlyとして残す。

## 完了条件

- R1〜R3の全回帰テストがgreenで、red→greenの実行記録が各PRにある。
- `uv run pytest backend/tests/test_founder_graph.py backend/tests/test_founder_graph_attachments.py -q` が `0 failed` である。Attachmentの環境skipは理由を記録する。
- `uv run pytest backend/tests -q` は直近統合で0 failedを確認する。Windows上のsymlink / Docker unavailable skipは理由を記録し、実機gateの代用とは扱わない。
- `python -X utf8 -m py_compile backend/dots/founder_graph.py`、`git diff --check`、相対Markdown link検査がgreenである。
- [founder-graph-pivot.md](founder-graph-pivot.md)のT-FG-05、T-FG-16、T-FG-18、T-FG-19、T-FG-23に対して、各sliceのテストとrollback境界が対応している。
- 外部AI、実ユーザーデータ、API key、Docker実機restoreをこのkernel計画の完了根拠にしない。これらは正本の後続Gateで検証する。

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-09-21 | 3回の実装・レビュー後に残った6領域を3sliceへ再分解し、transient attachment/local-ops failuresを分離 | High指摘が同じmoduleへの追加修正だけでは閉じず、planningへ差し戻されたため | FG-R1、FG-R2、FG-R3 |
| 2026-09-22 | FG-R3の実装境界を固定し、Source/SourceRevision value object、履歴validator、全NodeTypeのstatic projection allowlistを実装してfocused/backend suiteを再検査 | Sourceの論理原本と不変revisionを分離し、private fieldの外部返却境界をコードとテストで一致させるため | FG-R3 |
| 2026-09-22 | canonical SourceをGraphReadServiceのallowlistへ追加し、全NodeTypeのegress_policyをread viewへ反映 | domain projectionとMCP read surfaceのshareable判定を同じ契約へ揃え、Source追加後の未到達を解消するため | FG-R3、T-FG-07、T-FG-08 |
