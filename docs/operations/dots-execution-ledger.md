# Dots implementation execution ledger

最終更新: 2026-09-23
main SHA: `9844cebc4f89`
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
| Last merged PR | #199 |
| Last main smoke | focused backend 114 passed / 2 skipped、Docker Desktop Engine 29.8.0、Neo4j保存→停止→再起動→MCP検索を実機確認 |

## Task ledger

| Task | Status | Owner task | Branch | PR | Head SHA | Tests | Decision / Block | Updated at |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P0-01 | MERGED | root | main | #196 / #197 | `c8017f54d034` | planning, link, CI passed | none | 2026-09-23 |
| P0-02 | MERGED | root | main | #197 | `c8017f54d034` | ledger, task packet, CI passed | none | 2026-09-23 |
| P0-03 | READY | unassigned | - | - | `c8017f54d034` | issue alignment pending | none | 2026-09-23 |
| P1-SP-01 | REVIEW | schema_v2_spike_luna | delegated | - | - | fixture ready=True、blocking=0、migration preview files ready | none | 2026-09-23 |
| P2-SP-01 | MERGED | neo4j_runtime_probe_luna | delegated | - | - | Docker Desktop 29.8.0、Compose 5.5.1、Windows CLIで実機確認 | none | 2026-09-23 |
| P2-01/P2-03/P3-02 | MERGED | root | main | #199 | `9844cebc4f89` | Neo4j port/secret/read transaction修正、focused tests 114 passed / 2 skipped、MCP保存検索実機確認 | none | 2026-09-23 |
| P3/P5 audit | REVIEW | mvp_vertical_slice_audit_luna | delegated | - | - | default in-memoryの断絶、MCP egress条件、UI未接続を確認 | none | 2026-09-23 |

## Decision ledger

| Decision | Status | Stopped scope | Recommended default |
| --- | --- | --- | --- |
| Q-DM-01 | ADOPTED (MVP仮データ範囲) | none | schema v2を採用 |
| D-EXT-01 | OPEN | P5以降 | 合成データ接続を許可 |
| D-BACKUP-01 | OPEN | P8-SP-01以降 | アプリ層暗号化、同generationの別artifact |
| D-DELETE-01 | OPEN | P8-02以降 | Reportを残しunavailable表示 |
| D-LEGACY-01 | DEFERRED | P9-02 | inventory後に判断 |
| D-REAL-01 | OPEN | P9-03以降 | security review後に一件canary |
