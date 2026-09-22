# 意味単位の自動統合ワークフロー計画

更新日: 2026-09-22

## 背景

Dotsでは、変更が一区切りするたびに利用者がGit操作を指示しなくても、Codexが検査、意味単位のcommit、push、PR、mainへのmerge、main smokeまで完了させる運用が必要である。一方、Git hookはcommitやpushの局所イベントしか扱えず、受け入れ条件、CI、review、CEO決裁境界を判断できないため、mainへの自動統合の正本にはしない。

## ゴール

- 「一区切り」を、受け入れ条件、必須検査、セルフレビューが完了した意味単位として定義する。
- Dotsの全Codex taskが同じ完了手順を自動適用する。
- mainへの直接pushを避け、PRとCIを通してmainへ統合する。
- 利用者または別作業の変更を混入、復元、削除しない。

## 対象外

- CI失敗、競合、秘密情報、未決のCEO決裁境界がある変更の強制merge。
- あらゆるcommitを無条件でmainへ送るGit hook。
- Free、Standard、Pro、課金、複数利用者向け機能。

## 受け入れ条件

### US-FM-01 共通完了手順

Given 依頼された変更の受け入れ条件と必須検査が完了している
When Codexが意味単位の作業完了を検知する
Then 追加の許諾なしに対象変更だけをcommit、push、PR化し、CIとreview成功後にmainへmergeしてmain smokeを実行する。

### US-FM-02 安全停止

Given CI失敗、競合、秘密情報、対象不明、または未決のCEO決裁境界がある
When 自動統合手順がその状態を検出する
Then mergeせず、安全に可能な修正と診断を尽くしたうえで、停止位置と必要な判断を報告する。

### US-FM-03 意味単位の履歴

Given 複数の独立した目的を含む作業ツリーがある
When Codexが統合を開始する
Then 実装と対応テストを同じ意味単位にまとめ、対象ファイルを明示してstageし、目的別commitとPRへ分割する。

## 設計判断

1. 正本はproject-local Skillと`AGENTS.md`の必須規則にする。Git hookは採用しない。
2. mainへ直接pushせず、topic branch、PR、CI、reviewを経由する。
3. 一連の意味単位commitを残す場合はmerge commitを使う。
4. 作業中のcheckoutに別変更がある場合、main smokeは隔離worktreeで行う。
5. PR作成後は現在のCodex taskへPRをattachし、成果物との対応を保持する。

## 今回の統合順

1. 既存のDots名称変更commitをPR化してmainへ統合する。
2. 完了Skill、ルーティング、運用計画を統合する。
3. Founder Graphの仕様、データモデル、provenance境界を統合する。
4. Founder Graphの保存・検索kernelと対応テストを統合する。
5. 添付、runtime、Neo4j、MCPの各境界を依存順に統合する。
6. UI、運用スクリプト、セットアップ文書を対応機能とともに統合する。
7. 最新mainを隔離環境で検査し、Windows側Docker DesktopでEngine応答を再確認する。

各単位が500行を超える場合は、同一受け入れ条件を壊さずに分割できるか先に確認する。分割がテスト不能またはrollback不能な中間状態を作る場合は、その理由をPRへ明記する。

## 実装タスク

- FM-01: `finish-and-merge` Skillを追加し、`AGENTS.md`とskill indexから必須ルートにする。
- FM-02: 現在の作業ツリーを依存関係とrollback単位で棚卸しし、意味単位commitを作る。
- FM-03: 各commitを順番にPR化し、CI、review、merge、main smokeを閉じる。
- FM-04: Docker DesktopのWindows Engine応答を記録し、WSL連携はFounder Graph実機検証の開始条件として別途確認する。

## 検査

- Skillメタデータ検証。
- `git diff --check`。
- 各意味単位に対応するbackend、frontend、build、Storybook検査。
- 各PRの必須CI。
- merge後のmain smoke。

## 変更履歴

- 2026-09-22: 初版。Git hookではなくproject-local SkillとPRベースの自動統合を採用。
