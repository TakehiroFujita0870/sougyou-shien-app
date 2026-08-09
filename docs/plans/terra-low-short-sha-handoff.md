# Terra/low と短縮 SHA の連絡規約

## 目的

CEO室を `gpt-5.6-sol / low`、統合部と実装部を `gpt-5.6-terra / low` に固定し、通常のPR・レビュー・マージ・handoffで12文字short SHAを使う。完全SHAは内部の監査、rollback、collision、delivery failureだけに残す。

## 受け入れ条件

- Given: CEO室、統合部、各実装部のイベントを送る。When: model/thinkingを記載する。Then: CEO室は `gpt-5.6-sol / low`、統合部と実装部は `gpt-5.6-terra / low` であり、Luna選択、fallback、`model_unavailable`を要求しない。
- Given: PR_READY、PR_UPDATED、REVIEW_APPROVED、REVIEW_CHANGES_REQUESTED、MERGED、DEPENDENCY_READYを送る。When: SHAを記載する。Then: 通常payloadとfinalには12文字short SHAだけを表示し、統合レビュー時はPRの完全SHAと内部照合する。
- Given: audit、rollback、collision、delivery failureが発生する。When: 追跡情報を記録する。Then: 完全SHAと完全idempotency keyを内部記録に限定する。
- Given: CEO室向け `MERGED { org_health }` を送る。When: merge後handoffを報告する。Then: short SHA、部門状態要約、CEO action要求だけを含め、receiptの完全idempotency key一覧を含めない。
- Given: 部長が補助作業を必要とする。When: subagentを使う。Then: boundedかつnon-overlappingな範囲に限定し、部長がplanning、review、handoff closureを保持する。
- Given: CEO室がscope未限定の `CHANGE` を送る。When: 統合部が受信する。Then: 全担当のactive/review/next owner、idle capacity、conflict/unblock、未割当理由をscanし、WIP・所有権・依存に従う `ASSIGNMENT`、`CONTINUE`、`HOLD`、`CLOSE` を配信する。

## スコープ外

- runtime、API、外部サービス、既存WIP、PR #89、#120、#121の仕様または所有権の変更。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
|---|---|---|---|
| T-PROFILE-02 | `AGENTS.md`、handoff正本、計画のCEO例外とCHANGE scan訂正 | 検査: planning Exit Criteria、`git diff --check`、UTF-8 read-back | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
|---|---|---|---|
| CEO profile | CEO室だけをSol/lowにし、統合部と実装部はTerra/lowを維持する | 全担当Terra/lowはCEO例外を表せないため却下 | profile表とeventを訂正 |
| CHANGE処理 | scope未限定CHANGEは全社scan後に配分を決める | 単発Issueだけの判断はidle capacityと依存を見落とすため却下 | compact scanを必須化 |

## 検証

- `git diff --check` が成功する。
- 対象正本のactive規約に `gpt-5.6-luna`、`/ medium`、`model_unavailable`が残らないことを、計画文書自身を除外した検索で確認する。
- Skillのforward scenarioはlive PRを変更せず、受領前にfinalしない規約と12文字SHA表示を確認する。
