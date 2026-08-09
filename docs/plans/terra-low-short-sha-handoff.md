# Terra/low と短縮 SHA の連絡規約

## 目的

全担当を `gpt-5.6-terra / low` に統一し、通常のPR・レビュー・マージ・handoffで12文字short SHAを使う。完全SHAは内部の監査、rollback、collision、delivery failureだけに残す。

## 受け入れ条件

- Given: CEO室、統合部、各実装部のイベントを送る。When: model/thinkingを記載する。Then: すべて `gpt-5.6-terra / low` であり、Luna選択、fallback、`model_unavailable`を要求しない。
- Given: PR_READY、PR_UPDATED、REVIEW_APPROVED、REVIEW_CHANGES_REQUESTED、MERGED、DEPENDENCY_READYを送る。When: SHAを記載する。Then: 通常payloadとfinalには12文字short SHAだけを表示し、統合レビュー時はPRの完全SHAと内部照合する。
- Given: audit、rollback、collision、delivery failureが発生する。When: 追跡情報を記録する。Then: 完全SHAと完全idempotency keyを内部記録に限定する。
- Given: CEO室向け `MERGED { org_health }` を送る。When: merge後handoffを報告する。Then: short SHA、部門状態要約、CEO action要求だけを含め、receiptの完全idempotency key一覧を含めない。
- Given: 部長が補助作業を必要とする。When: subagentを使う。Then: boundedかつnon-overlappingな範囲に限定し、部長がplanning、review、handoff closureを保持する。

## 変更範囲と非目標

- 変更: `AGENTS.md`、handoff正本、`handoff-closure` Skill。
- 非目標: runtime、API、外部サービス、既存WIP、PR #89、#120、#121の仕様または所有権の変更。

## 検証

- `git diff --check` が成功する。
- 対象正本のactive規約に `gpt-5.6-luna`、`/ medium`、`model_unavailable`が残らないことを、計画文書自身を除外した検索で確認する。
- Skillのforward scenarioはlive PRを変更せず、受領前にfinalしない規約と12文字SHA表示を確認する。
