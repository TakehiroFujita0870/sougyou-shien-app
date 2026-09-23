# Dots implementation execution ledger

最終更新: 2026-09-23
main SHA: `6db8ad24ddd2`
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
| Current phase | P3/P8 MVP vertical slice |
| Last merged PR | #214 |
| Last main smoke | backend `uv run --isolated pytest -q`: 357 passed / 17 skipped、isolated Neo4j save-stop-restart-search smoke passed、Neo4j database dump/load and restore query passed |

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
| P3-01-REAL | MERGED | root | main | #211 | `f55266eb8c41` | isolated Neo4j save, stop, same-volume restart, Idea and Source search passed | Compose live manifest and backup / restore remain | 2026-09-23 |
| DM-01 | MERGED | root | main | #213 | `99793152125d` | schema v2 domain contract tests passed、backend 354 passed / 17 skipped | Neo4j persistence migration remains | 2026-09-23 |
| P3-02 | MERGED | root | main | #214 | `6db8ad24ddd2` | max-2-hop in-memory / Neo4j / MCP tests passed、backend 357 passed / 17 skipped | Luna rerank evaluation remains | 2026-09-23 |
| P8-SP-01-NEO4J | RUNNING | root | codex/p8-backup-restore-evidence | - | - | isolated Neo4j/system dump, load, restore query passed; temporary resources removed | Attachment and same-generation manifest hash remain | 2026-09-23 |

## Decision ledger

| Decision | Status | Stopped scope | Recommended default |
| --- | --- | --- | --- |
| Q-DM-01 | ADOPTED (MVP仮データ範囲) | none | schema v2を採用 |
| D-EXT-01 | OPEN | P5以降 | 合成データ接続を許可 |
| D-BACKUP-01 | OPEN | P8-SP-01以降 | アプリ層暗号化、同generationの別artifact |
| D-DELETE-01 | OPEN | P8-02以降 | Reportを残しunavailable表示 |
| D-LEGACY-01 | DEFERRED | P9-02 | inventory後に判断 |
| D-REAL-01 | OPEN | P9-03以降 | security review後に一件canary |
