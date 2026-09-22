# Founder Graph T-FG-26 local UI / runtime 監査

最終検証日: 2026-09-22

## 要望 / ゴール / 成功指標

要望: T-FG-26のbackup、restore、delete、Markdown / JSON export UIについて、現行のsafe export、offline manifest、既存Report export intentが満たす範囲と、単独利用者の全ownerデータを扱うlocal runtimeに不足する範囲を分離する。

ゴール: shareable exportを外部送信可能なsafe projectionとして維持しつつ、full owner backupを同じ出力として誤用しないUI/runtime実装の前提を記録する。

成功指標: T-FG-26の各操作について既存成果物、欠落runtime、必要な実機証跡、データ分類が一意に読め、safe exportを全owner backupの証跡と扱う記述が0件である。

## ユーザーストーリーと受け入れ条件

### US-26-01 shareable exportを明示する

As a 単独利用者, I want ReportVersionまたはshareable graph projectionをJSON / Markdownで取り出したい, so that 外部へ渡してよい範囲を確認できる。

Given: read projectionまたはReportDiffのexport intentにshareable dataだけがある。

When: UIがexport requestを作る。

Then: format、scope、projectionが明示され、local_only、contact、private_notes、source_text、instruction pathをファイル候補へ含めない。

### US-26-02 full owner backupをsafe exportと分離する

As a 単独利用者, I want 自分の全ownerデータをローカル復旧用に保管したい, so that privateなPerson、連絡先、原文、revisionも失わない。

Given: 全ownerデータにはshareableとlocal_onlyの両方がある。

When: backupまたはrestoreを選ぶ。

Then: UI/runtimeはshareable exportをfull backupと表示せず、private local archiveの保護方式と復旧対象を確定するまでfull backupを開始しない。

### US-26-03 destructive operationを復旧可能にする

As a 単独利用者, I want deleteの影響を確認してから実行したい, so that current search、report参照、export、backupの整合性を失わない。

Given: node、Source、attachment、ReportVersion参照が存在する。

When: delete UIを選ぶ。

Then: physical deleteを公開せず、soft deleteと依存影響のpreviewを示し、成功後はcurrent searchと外部projectionから除外し、監査とrestore境界を残す。

## 現在の証跡と判定

| T-FG-26領域 | 現在の証跡 | 未実装または未検査のruntime | 判定 |
| --- | --- | --- | --- |
| shareable graph JSON / Markdown | `founder_graph_export.py`と8件のfocused test。owner、allowlist、bounded read、size、deterministic outputを検査 | FastAPI route、MCP tool、ファイル保存、ダウンロードUI、Neo4j dataとのlive接続 | local contractのみ |
| ReportVersion export intent | `FounderGraphReportDiff.jsx`が`format=json|markdown`、`scope=report_versions`、`projection=shareable`を作る | `onExportRequest`のApp/runtime実装、実ファイル生成、download、failure/retryのend-to-end検査 | UI intentのみ |
| offline JSON manifest | `verify_export_backup.py`とmanifest focused test。hash、owner、count、path、symlink、dry-runを検査 | safe export生成からmanifest作成までのruntime配線、Neo4j dump/load、隔離restore、再起動後read一致 | offline contractのみ |
| full owner backup / restore | T-FG-26の受け入れ条件に全owner data exportがある | private local archiveのformat、OS保護または暗号化方針、attachment inclusion、Neo4j dumpとの一致、restore UI | 未設計 |
| delete UI / propagation | kernelのsoft-delete・revision契約と既存attachment検査がある | Founder Graph用delete command、impact preview、UI、current search/report/export/backupへの実伝播 | 未実装 |

## 契約上のギャップ

`founder_graph_export.py`は意図的にshareable projectionだけを出力する。`founder-graph-backup-manifest-v1`もそのsafe JSONを検証対象にする。そのため、privateな名刺連絡先、local_only source text、instruction metadata、raw provenanceを含む「全ownerデータ」の復旧証跡にはならない。

既存のReportVersion export intentも`scope=report_versions`かつ`projection=shareable`であり、graph全体backup、attachment export、Neo4j dump、restore commandではない。この区別をUIコピー、API contract、運用手順の全てで維持する。

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| Q-26-01 | full owner private archiveはOSアカウント保護だけに依存するか、アプリ層の暗号化を必須にするか | 利用者兼製品責任者 | T-FG-26実装開始前 |
| Q-26-02 | attachment本体、Neo4j dump、safe JSON manifestを一つのrestore unitに束ねるか、世代IDで別artifactとして管理するか | 利用者兼製品責任者 | T-FG-26実装開始前 |
| Q-26-03 | Source deleteで参照を持つReportVersionを削除せずunavailable表示にする既定を確認するか | 利用者兼製品責任者 | delete UI設計前 |

## スコープ外

- React、FastAPI、MCP、Neo4j、backup script、delete commandの実装変更。
- 実データ、個人連絡先、attachment、資格情報を使うbackup / restore。
- 暗号アルゴリズム、鍵保管、OS permissionの方式選定。
- Docker / Neo4j実機のdump、load、再起動試験。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T26-AUD-01 | safe export、Report export intent、offline manifestの境界監査 | 検査: `rg -n "shareable|full owner|ReportVersion export|未設計" docs/plans/founder-graph-t26-runtime-audit.md` が各1件以上 | 既知 |
| T26-AUD-02 | full owner archiveとdeleteに関する決定待ち質問 | 検査: Q-26-01からQ-26-03が各1件以上あり、実装タスクが決定前に存在しないことをレビューする | 既知 |
| SP-26-01 | private local archiveの保護、attachment、Neo4j dump整合を合成fixtureで評価 | 検査: Q-26-01とQ-26-02の決定後、private dataを外部送信せずにcreate / verify / isolated restoreの試験結果を記録する | 未知・先行スパイク |
| SP-26-02 | soft delete impactとrestore表示を合成fixtureで評価 | 検査: Q-26-03の決定後、search、ReportVersion参照、safe export、full backupでの表示を照合する | 未知・先行スパイク |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| T26-ADR-01: export分類 | shareable exportとprivate local archiveを別contractにする。外部連携安全性と復旧完全性の目的が異なる | safe exportをfull backupと扱う。privateデータを失うか、safe boundaryを緩めるため却下 | 現行safe exportは外部送信可能な確認用に限定する |
| T26-ADR-02: Report export | ReportDiffのexport intentはreport_versions/shareableのまま保持する | graph backupのUIとして再利用する。scopeとprojectionを誤表示するため却下 | 実ファイル化しても全owner backupには昇格させない |
| T26-ADR-03: destructive deletion | full archiveの復旧契約とimpact previewが通るまでFounder Graph physical deleteを公開しない | 既存の汎用UI deleteを流用する。revision、evidence、attachmentへの影響を表現できないため却下 | soft delete設計はQ-26-03後の独立sliceにする |

## 実装メモ

- 計画タスク: T26-AUD-01, T26-AUD-02
- 受け入れ条件: US-26-01, US-26-02, US-26-03
- 追加テスト: なし。既存safe export / backup manifest / report export intentを監査した文書限定sliceである。
- API互換性: 影響なし。
- 検査結果: `uv run --isolated --python 3.14 pytest backend/tests/test_founder_graph_backup_manifest.py -q` は `9 passed, 1 skipped`、同テストと`test_founder_graph_local_ops.py`のfocused実行は `32 passed, 3 skipped`。`uv run --isolated --python 3.14 python -m py_compile scripts/founder-graph/verify_export_backup.py backend/tests/test_founder_graph_backup_manifest.py`、`uv run --isolated --python 3.14 python scripts/founder-graph/validate_local_ops.py --root .`、`git diff --check` は成功した。
- 文書監査: `docs/plans/founder-graph-export.md`の`## 実装メモ`は1節で、`docs/operations/founder-graph-local.md`もsafe JSON manifest節は1節だった。runbookのNeo4j `capture-manifest` / `verify-restore`契約とsafe JSON `verify_export_backup.py`契約は別artifactであり、同一manifestとして扱わない。
- 契約差分: 現行`verify_export_backup.py`はexport top-levelの`owner_id`が欠落していても、`build_manifest`へ渡されたownerをmanifestへ記録して検証を通す。manifest入力によるowner境界は検査できるが、export bytes単独のowner provenanceは証明できないため、full owner backupの完了根拠にはしない。Q-26-01〜03の決定や実装変更は行わない。

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-09-22 | T-FG-26のlocal UI / runtime監査を追加 | safe exportをfull owner backupと誤認せず、決定待ちを実装前に明示するため | T26-AUD-01、T26-AUD-02、SP-26-01、SP-26-02 |
