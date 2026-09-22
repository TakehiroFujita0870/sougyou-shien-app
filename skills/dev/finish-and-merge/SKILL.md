---
name: finish-and-merge
description: Dotsの変更が意味単位で完了したとき、対象外の変更を守りながら検査、commit、push、PR、review、mainへのmerge、main smokeまで自動で閉じる。
---

# Finish and Merge

## 目的

利用者が毎回Git操作を指示しなくても、依頼された変更を安全な意味単位でmainへ届ける。単にファイル編集が止まった時点ではなく、受け入れ条件、必要な検査、セルフレビューが完了した時点を「一区切り」とする。

## 適用条件

- 利用者から停止、未commit、下書き保持の指示がない。
- その意味単位の必須受け入れ条件が満たされ、対象範囲に未完了作業がない。
- CEO決裁境界、秘密情報、競合、必須検査失敗が残っていない。

適用条件を満たしたら、追加の許諾を求めずこの手順を開始する。

## 手順

1. `git status --short`、`git diff --stat`、`git diff --check`で変更全体を確認する。
2. 自分が担当した変更と、利用者または別作業の変更を分ける。対象ファイルを明示してstageし、`git add .`、`git add -A`、対象外の復元を行わない。
3. 変更を、単独で目的を説明でき、単独で戻せる意味単位に分ける。実装とそのテスト、仕様とその受け入れ条件は同じ単位に含める。
4. `AGENTS.md`と工程スキルが要求する検査を実行する。実行不能な検査は理由、未検査範囲、代替検査をPRへ記録する。
5. staged diff、秘密情報、生成物、無関係な整形をセルフレビューする。問題があれば修正して再検査する。
6. 意味単位ごとにcommitする。commit messageは目的を一文で表す。
7. topic branchをoriginへpushする。mainへ直接pushしない。
8. PR説明に目的、受け入れ条件と実装の対応、検査結果、影響とrollbackを書く。日本語本文は作成前後に文字化け検査を行う。
9. PR作成後はPR URLを現在のCodex taskへattachする。CI、PR head SHA、base、差分を確認し、新しいpushがあれば以前のreviewを無効として再確認する。
10. 必須CIが成功し、未解決のreview、競合、決裁境界がなければPRをmainへmergeする。意味単位のcommitを残す必要がある一連の変更ではmerge commitを使う。
11. origin/mainをfetchし、清潔なmain checkoutまたは隔離worktreeでmain smokeを実行する。作業中の別変更があるcheckoutを強制的に切り替えない。
12. merge後handoffがある場合は`handoff-closure`を使い、送達と受領確認まで閉じる。最後にPR番号、12文字short SHA、検査結果、残課題を利用者へ伝える。

## 自動mergeを止める条件

- 必須CIまたはローカル検査が失敗している。
- 秘密情報、個人情報、意図しない大容量生成物を検出した。
- mainとの競合、破壊的API・データ移行、外部公開、支出、契約、実外部サービスへの初回接続など、未決のCEO決裁境界がある。
- 変更の所有者または対象範囲を安全に特定できない。
- 利用者が停止、review待ち、未commit保持を指示した。

停止時は安全に進められる診断と修正を尽くし、止めた場所、理由、必要な判断を具体的に報告する。

## Exit Criteria

- [ ] 変更が意味単位でcommitされ、対象外変更を含んでいない。
- [ ] branchがoriginへpushされ、PRが現在のtaskへattachされている。
- [ ] 必須CIとreviewが完了している。
- [ ] PRがmainへmergeされ、main smokeが成功している。
- [ ] 利用者向け報告にPR、12文字short SHA、検査、残課題がある。
