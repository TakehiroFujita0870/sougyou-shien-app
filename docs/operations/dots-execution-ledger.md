# Dots implementation execution ledger

最終更新: 2026-09-23
main SHA: `8c38747d8914`
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
| Current phase | P2/P3 MVP vertical slice |
| Last merged PR | #208 |
| Last main smoke | backend `uv run --isolated pytest -q`: 348 passed / 17 skipped、WSL preview script contract passed、MCP tunnel static contract passed、runtime/MCP focused tests 19 passed |

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

## Decision ledger

| Decision | Status | Stopped scope | Recommended default |
| --- | --- | --- | --- |
| Q-DM-01 | ADOPTED (MVP仮データ範囲) | none | schema v2を採用 |
| D-EXT-01 | OPEN | P5以降 | 合成データ接続を許可 |
| D-BACKUP-01 | OPEN | P8-SP-01以降 | アプリ層暗号化、同generationの別artifact |
| D-DELETE-01 | OPEN | P8-02以降 | Reportを残しunavailable表示 |
| D-LEGACY-01 | DEFERRED | P9-02 | inventory後に判断 |
| D-REAL-01 | OPEN | P9-03以降 | security review後に一件canary |
