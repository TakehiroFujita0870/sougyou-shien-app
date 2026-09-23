# Dots implementation execution ledger

最終更新: 2026-09-23
main SHA: `793f7c593f95`
active goal: Founder Graph MVP

## 運用

- 一行を一taskとし、会話内容ではなくGitHub Issue、PR、12文字short SHA、test結果を記録する。
- statusは`READY`、`RUNNING`、`REVIEW`、`BLOCKED`、`MERGED`だけを使う。
- root coordinatorだけがtask status、owner、dependencyを更新する。
- workerは自分のhandoffに結果を返し、このledgerを直接変更しない。
- secret、個人情報、会話原文、長いtest logを記録しない。

## Goal

| Field | Value |
| --- | --- |
| Objective | `docs/plans/dots-implementation-master-plan.md`のDefinition of Doneを全て満たす |
| Model | `gpt-5.6-luna` |
| Reasoning | `max` |
| Coordinator slots | 1 |
| Worker slots | 最大3 |
| Current phase | P1/P3/P4/P5/P8 MVP vertical slice |
| Last merged PR | #233 |
| Last main smoke | backend `uv run --isolated pytest -q`: 387 passed / 17 skipped、frontend `npm.cmd test -- --run`: 322 passed、frontend build and Storybook build passed; schema v2 migration/rollback、v2 read/write parity、isolated Neo4j save-stop-restart-search and database dump/load restore query passed; Appの明示Graph live read接続点、検索入力、本人確認済みPerson統合境界、ReportVersion親版検証、Compose再起動manifest検査を追加 |

## Task ledger

| Task | Status | Owner task | Branch | PR | Head SHA | Tests | Decision / Block | Updated at |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P0-01 | MERGED | root | main | #196 / #197 | `c8017f54d034` | planning, link, CI passed | none | 2026-09-23 |
| P0-02 | MERGED | root | main | #197 | `c8017f54d034` | ledger, task packet, CI passed | none | 2026-09-23 |
| P0-03 | READY | unassigned | - | - | `c8017f54d034` | issue alignment pending | none | 2026-09-23 |
| P1-SP-01 | MERGED | schema_v2_spike_luna | delegated | #200 | `d26dbd7bd0a8` | fixture ready=True、blocking=0、migration preview files merged | none | 2026-09-23 |
| P2-SP-01 | MERGED | neo4j_runtime_probe_luna | delegated | - | - | Docker Desktop 29.8.0、Compose 5.5.1、Windows CLIで実機確認 | none | 2026-09-23 |
| P2-01/P2-03/P3-02 | MERGED | root | main | #199 | `9844cebc4f89` | Neo4j port/secret/read transaction修正、focused tests 114 passed / 2 skipped、MCP保存検索実機確認 | none | 2026-09-23 |
| P3/P5 audit | MERGED | mvp_vertical_slice_audit_luna | delegated | #199 / #201 | `0c3892614b48` | persistent stdio opt-in、MCP egress条件、tool schemaを反映 | D-EXT-01で実ChatGPT登録は保留 | 2026-09-23 |
| P3-03 | MERGED | root | main | #201 | `0c3892614b48` | 8 write tools publish actionable schemas、25 focused tests passed | none | 2026-09-23 |
| CI-01 | MERGED | root | main | #203 | `64fdcbbc56d1` | PR quality 53s passed; manual CI run #35746980996 passed in 4m50s | none | 2026-09-23 |
| LEG-01 | MERGED | root | main | #204 | `c2b1c6d1432d` | candidate inventory published; no deletion performed; path corrected | D-LEGACY-01 remains deferred | 2026-09-23 |
| P2-04 | MERGED | root | main | #206 | `eaadc0c4d526` | configured FastAPI / stdio runtime selection; focused runtime tests passed | real Neo4j restart smoke remains | 2026-09-23 |
| P3-01 | MERGED | root | main | #207 | `4394a891fc87` | Idea、conversation Source、SourceRevision atomic capture; backend 348 passed / 17 skipped | real Neo4j restart fetch remains | 2026-09-23 |
| RT-04 | MERGED | root | main | #208 | `8c38747d8914` | WSL preview uses `dots.main:app`; script and tunnel contract checks passed | none | 2026-09-23 |
| LEDGER-01 | MERGED | root | main | #209 | `7881228a80e4` | execution ledger synchronized with main after PR #209 | none | 2026-09-23 |
| LEDGER-02 | MERGED | root | main | #210 | `fc64d057c6e0` | execution ledger head synchronized after PR #209 ledger update | none | 2026-09-23 |
| P3-01-REAL | MERGED | root | main | #211 | `f55266eb8c41` | isolated Neo4j save, stop, same-volume restart, Idea and Source search passed | Compose live manifest and Attachment archive remain | 2026-09-23 |
| DM-01 | MERGED | root | main | #213 | `99793152125d` | schema v2 domain contract tests passed、backend 354 passed / 17 skipped | Neo4j persistence migration remains | 2026-09-23 |
| P3-02 | MERGED | root | main | #214 | `6db8ad24ddd2` | max-2-hop in-memory / Neo4j / MCP tests passed、backend 357 passed / 17 skipped | Luna rerank evaluation remains | 2026-09-23 |
| P5-SP-01 | MERGED | root | main | #216 | `5f83fb2bf8b8` | synthetic MCP capture, search, fetch on one stdio connection; backend 358 passed / 17 skipped | D-EXT-01 real ChatGPT registration remains | 2026-09-23 |
| P4-02 | MERGED | root | main | #217 | `9ade328d1af3` | synthetic contact CSV all-row validation, owner/private boundary, idempotent write; backend 361 passed / 17 skipped | P4-SP-03 namesake evaluation remains | 2026-09-23 |
| P8-SP-01-NEO4J | MERGED | root | main | #215 | `6c91b108d9ed` | isolated Neo4j/system dump, load, restore query passed; temporary resources removed | D-BACKUP-01 Attachment and same-generation manifest remain | 2026-09-23 |
| P1-03 / DM-02 | MERGED | root | main | #218 | `32097ef3a3ea` | schema v2 migration, idempotent rerun, non-destructive rollback passed on isolated Neo4j; backend 363 passed / 17 skipped | Existing-data conversion and v2 write/read parity remain | 2026-09-23 |
| P4-SP-03-A | MERGED | p4_namesake_relation_next | main | #220 | `69f9628c6fea` | synthetic namesake candidates, top-3 recall 1.00, automatic merges 0; backend 367 passed / 17 skipped | Real Luna ranking and confirmed-only merge API/UI remain | 2026-09-23 |
| P6-02-local | MERGED | p6_local_report_next | main | #221 | `d6977ed62961` | explicit three-way follow-up classification, immutable snapshot; backend 375 passed / 17 skipped | D-EXT-01 external connection and persistence integration remain | 2026-09-23 |
| P7-01-read | MERGED | p7_graph_live_ui_next | main | #222 | `63ade9a5171a` | live-read client state/retry tests 18 focused; frontend 320 passed and build passed | App wiring, search input, correction/history remain | 2026-09-23 |
| P1-04 | MERGED | root | main | #224 | `de4d6d77b75a` | v2 all-node-type manifest and representative search parity; backend 378 passed / 17 skipped | Existing-data conversion, Compose live manifest, default Neo4j switch remain | 2026-09-23 |
| P7-01-D | MERGED | root | main | #226 | `b90f2319b18c` | Appの明示クライアント接続、Graph live read focused 7 passed、frontend 321 passed、build/Storybook passed、backend 378 passed / 17 skipped | 検索入力、訂正/履歴、実ChatGPT接続は未着手またはD-EXT-01で保留 | 2026-09-23 |
| P4-03-C | MERGED | p4_relation_confirm | main | #228 | `ad70463e2fc8` | 明示confirmed + 根拠IDのPerson統合、敗者archived、冪等再送、MCP HTTP/stdio契約、Neo4j未対応時の明示拒否; backend 379 passed / 17 skipped | Neo4j原子統合、既存関係付替え、統合UIは未実装 | 2026-09-23 |
| RPP-01/RPP-02 | MERGED | p6_parent_validation | main | #230 | `bf204638753f` | ReportVersion親版の存在・種類・ownerをメモリ/Neo4j互換保存前に検証、同owner親版を許可; backend 387 passed / 17 skipped | 差分計算、親版比較UI、Deep Research接続は未実装 | 2026-09-23 |
| P7-01-E | MERGED | p7_graph_search_input | main | #232 | `945ad46b8335` | Graph検索入力、submit時のみ明示local clientへ依頼、focused 5 passed、frontend 322 passed、build passed | 訂正/履歴UI、実ChatGPT接続は未実装またはD-EXT-01で保留 | 2026-09-23 |
| P2-02/P2-03 | MERGED | p2_compose_manifest | main | #233 | `793f7c593f95` | Compose live volume名と停止前後synthetic manifest一致の手順・回帰検査、focused 23 passed / 2 skipped、static validator passed | Attachment同generation、実データ、backup decisionは未完了 | 2026-09-23 |

## Decision ledger

| Decision | Status | Stopped scope | Recommended default |
| --- | --- | --- | --- |
| Q-DM-01 | ADOPTED (MVP仮データ範囲) | none | schema v2を採用 |
| D-EXT-01 | OPEN | P5以降 | 合成データ接続を許可 |
| D-BACKUP-01 | OPEN | P8-SP-01以降 | アプリ層暗号化、同generationの別artifact |
| D-DELETE-01 | OPEN | P8-02以降 | Reportを残しunavailable表示 |
| D-LEGACY-01 | DEFERRED | P9-02 | inventory後に判断 |
| D-REAL-01 | OPEN | P9-03以降 | security review後に一件canary |
