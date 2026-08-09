# エージェント作業指示

## 適用範囲

このファイルはリポジトリ全体に適用する。より深いディレクトリに `AGENTS.md` がある場合は、その指示を優先する。継承資料である `docs/inherited/` は参照専用であり、明示的な依頼なしに変更しない。

## 作業開始時

1. `skills/dev/INDEX.md` を読み、現在の工程のスキルを読む。
2. 機能追加、仕様変更、修正、技術選定では、先に planning を実施して計画文書と受け入れ条件を用意する。
3. 実装では implementation の再帰ループに従う。テストとセルフレビューの Exit Criteria を満たすまでPRを出さない。3周しても満たせない場合は、実装を止めて planning に差し戻す。
4. 既存の未コミット変更は利用者または別作業のものとして扱う。対象外のファイルを変更、ステージ、復元しない。

## プロダクト段階とAIモデル

- 初回リリースはFreeとStandardだけを対象とする。Proの自動調査・メール配信は、利用状況と原価データが蓄積するまで実装しない。
- モデル、API、料金、廃止予定を変更するときは、先に [`docs/operations/model-lifecycle.md`](docs/operations/model-lifecycle.md) を読む。
- モデルIDを画面、API、プロンプトへ分散してハードコードしない。プロバイダー別アダプターと一元的なモデルカタログを経由する。
- 開発時のClaude互換対象は `claude-opus-5`、`claude-sonnet-5`、`claude-haiku-4-5-20251001` とする。Standardのユーザー既定モデルは `gpt-5.6-terra` とし、利用可能モデルからユーザーが選択できる設計にする。
- モデル更新は公式情報の検知、評価、PR作成までを将来自動化してよい。本番の既定モデル変更、料金境界変更、廃止モデルからの移行を無審査で自動マージしない。
- APIキー、課金開始、実ユーザーデータの外部AI送信はCEO決裁が完了するまで行わない。

## 変更規律

- 1 PR は単一の目的に限定し、差分500行以内かつレビュー30分以内を目安にする。超える場合は計画を分解する。
- 受け入れ条件、テスト、実装の対応をPR説明に書く。
- 秘密情報、認証情報、個人情報をコード、ログ、テストフィクスチャ、Git履歴に残さない。`.env` はコミットしない。
- DBマイグレーションは前方・後方互換性、ロールバック方法、既存データへの影響をPR説明に記載する。
- APIの破壊的変更は互換方針を計画で承認されるまで実施しない。
- README、セットアップ手順、仕様、計画に影響する変更は同じPRで更新する。

## 部門間のイベント駆動連携

- 定期ポーリングを部門間連携の正本にしない。PR作成、PR更新、レビュー差し戻し、CI完了、マージ、ブロックの発生元が、発生直後に担当タスクへメッセージを送って次工程を起動する。
- 作業開始時に [`docs/operations/department-handoffs.md`](docs/operations/department-handoffs.md) を読み、自部門の送信責任と応答責任を確認する。会話履歴だけを引き継ぎ情報にしない。
- 実装部門はPR作成またはhead SHA更新後、統合・リリース管理部へ `PR_READY` を送る。統合部は `REVIEW_CHANGES_REQUESTED`、`MERGED`、`BLOCKED` のいずれかを担当部へ返す。
- メッセージにはリポジトリ、Issue、PR、head SHA、変更目的、検査結果、CEO決裁境界の有無を含める。秘密情報、認証情報、個人情報を含めない。
- 送信先タスクが停止中でも、メッセージ送信によって新しいturnを起動する。送信不能時はPRコメントへ同じ非機密情報を記録し、管理タスクへ `BLOCKED` を送る。
- 統合部は通知されたhead SHAだけをレビューする。新しいSHAがpushされた場合、以前の承認を無効とし、新しい `PR_READY` を要求する。
- 通常経路では、実装部は `PR_READY` を統合・リリース管理部だけへ送る。PR作成時点でCEO室へ通知しない。
- 統合部はmergeとmain smoke完了後に `MERGED` をCEO室と担当部へ送る。CEO室向けpayloadにはPR、目的、ユーザー影響、検査、ロールバック、次の依存作業を含め、詳細diffはPRリンクで参照させる。
- mergeとsmoke成功の同一turnで、統合部は `MERGED`、必要な`DEPENDENCY_READY` delivery、`ORG_HEALTH`、CEO室の`PORTFOLIO_DIRECTIVE`、`ASSIGNMENT` delivery、受信部のactiveまたは`BLOCKED(model_unavailable)`を順に完了する。いずれかが未完了ならmerge後handoffは未完了であり、次のPRレビューを開始しない。
- PR時点でCEO室へ `BLOCKED` または `DECISION_REQUIRED` を送るのは、外部公開、支出、契約、法務、個人情報送信、実外部サービス初期接続、破壊的API/データ移行、部門間仕様衝突、P0セキュリティ/データ損失、main回帰/revert判断、500行超または複数目的で分割判断が必要な場合に限る。
- CI失敗と通常のP1/P2は担当部と統合部だけで解決し、CEO室へ送らない。

### 依存契約のhandoff

- 統合部は `MERGED` 時にnext_dependenciesが空でなければ、CEO室への報告と同時に次担当部へ `DEPENDENCY_READY` を送る。送信成功までmerge後handoffは完了ではない。
- 次担当が明確なら統合部が直接起動する。未割当、優先順位競合、新scope、CEO境界だけはCEO室へ `DECISION_REQUIRED` を送る。
- 統合・リリース管理部の実行プロファイルは `gpt-5.6-terra / medium` とする。利用不能時だけ管理タスクへ `BLOCKED` を送り、無断で別プロファイルへ変更しない。

### Issue・PRリソース管理

- 統合・リリース管理部がIssue assignment、WIP制限、依存順、変更ファイル所有権を決める。未割当Issueを実装部が独自に着手しない。
- 実装部の開始条件は統合部からの `ASSIGNMENT` または `DEPENDENCY_READY` である。
- 会話体験・プロジェクト部はchat/project workflow/data-context、プロダクトUI・デザインシステム部はsurface/layout/nav/tokens/a11y primitives、品質・プロダクト運用部は独立検証、基盤・認証部はauth/runtime、事業設計・調査部はdomain/API contractsを所有する。
- `App.jsx` とshared styleの同時変更は禁止する。両方が必要な場合、統合部が先にファイル所有権と時分割を明記する。
- 各実装部のWIP上限はレビュー待ち1PRと実装中1件である。統合部はレビューキューを優先して空にする。

### 全社ポートフォリオ管理と要件決定

- CEO室は全社ポートフォリオ管理・要件決定を所有し、実装には介入しない。優先順位、Issue配分、WIP再配分、停止・再開、部門境界を `PORTFOLIO_DIRECTIVE` で統合部へ指示する。
- 統合・リリース管理部は、CEO室の指示を実装部向けの `ASSIGNMENT` または `DEPENDENCY_READY` に翻訳し、レビュー、配分、handoffを所有する。実装部は割当済みスコープだけを実装する。
- 統合部は、PR mergeとsmoke成功、merge後にnext_dependenciesが空かつidle部門と未割当ready Issueが同時にある、部門WIPが0または上限超、P0 BLOCKED、同一ファイル所有権競合、依存先未割当、またはCEO決裁境界の直後だけ、全社状態を `ORG_HEALTH` としてCEO室へ送る。payloadにはmain SHA、merge source、各部active/idle/WIP、review queue、ready/unassigned Issue、dependency blocks、所有権衝突、次の配分候補、モデルavailability、mergeが解放した作業を含める。定期ポーリングを追加しない。同じstate fingerprintは二重送信しない。
- `REQUIREMENT_REQUEST` は、P0の実装/受入条件が未決、複数部の設計衝突、価格・外部接続・個人情報・法務などCEO決裁が必要な場合だけCEO室からユーザーへ送る。通常の進捗確認、CI失敗、P1/P2は対象外とする。

### 役割別モデルプロファイル

- CEO室と統合・リリース管理部は `gpt-5.6-terra / medium` を使う。会話体験・プロジェクト部、プロダクトUI・デザインシステム部、品質・プロダクト運用部、基盤・認証部、事業設計・調査部は `gpt-5.6-luna / low` を使う。
- 指定モデルが利用不能な場合だけ、担当部は `BLOCKED`（`reason: model_unavailable`）を統合部へ送る。統合・リリース管理部自身が利用不能な場合はCEO室へ同じ理由で送る。無断で `gpt-5.6-terra` その他のプロファイルへ切り替えてはならない。
- `ASSIGNMENT` と `DEPENDENCY_READY` には `model` と `thinking` を必須とし、送信側は同じoverrideで受信部の新turnを起動する。

## Windows / PowerShell の実行規約

- Windows版Codexでは PowerShell を標準シェルとし、Git Bash は bash 前提の限定検査にだけ使う。詳細な安全例、禁止例、診断手順、Ubuntu CIとの差分は [`docs/operations/windows-powershell.md`](docs/operations/windows-powershell.md) を正本とする。
- 検索は `rg`、パスを受け取る PowerShell コマンドは `-LiteralPath`、UTF-8 文書の読取は `-Encoding UTF8` を使う。編集は `apply_patch` だけで行い、`echo`、`cat`、リダイレクトによる編集をしない。
- 非ASCIIのIssue/PR本文をPowerShellからネイティブCLIへ直接パイプしない。`apply_patch`で作成したBOMなしUTF-8ファイルを`--body-file <ファイル>`で読ませるか、Node.js/PythonからUTF-8 `Buffer`を`spawn`の`input`へ渡す。`$OutputEncoding`だけを安全策としない。
- 外部本文の更新前と更新直後のAPI read-backで、3文字以上連続する疑問符、U+FFFD、日本語文字数、必須見出しを検査する。異常時は更新を止め、復元して報告する。
- 新規開発はWSL内のLinux native cloneを主要環境にし、`/mnt/c`配下に`node_modules`や`.venv`を作らない。起動、検査、Git同期、systemd user serviceの正本は[`docs/operations/wsl-development.md`](docs/operations/wsl-development.md)とする。
- PowerShell利用開始時は`. .\scripts\powershell\Initialize-Utf8Preflight.ps1`をdot-sourceし、外部CLI更新前に`Test-Utf8Preflight`を通す。利用法と本文送信の停止条件は[`docs/operations/windows-powershell.md`](docs/operations/windows-powershell.md)を正本とする。
- 削除・移動はシェルをまたがず、再帰操作の前に絶対パスを検証する。作業変数に `HOME`、`home`、`CODEX_HOME` を使わない。

## 検査

変更範囲に応じて、PR前に以下を実行し、結果をPR説明に記載する。

```powershell
npm run test
npm run build
npm run build-storybook
uv run pytest
git diff --check
```

依存関係の変更がある場合は、ロックファイルを同期する。実行できない検査は、実行できない理由、未検査範囲、代替検査をPR説明に明記する。CI失敗を放置して次の作業を始めない。

## PR説明の最小様式

```md
## 目的

## 受け入れ条件と実装
- US-...: <条件> → <変更箇所・テスト>

## 検査結果
- <コマンド>: <結果>

## 影響とロールバック
- DB / API / ドキュメント: <影響なし、または方針>
```

## 禁止事項

- 受け入れ条件なしに実装を開始すること。
- 再現手順なしに不具合を修正すること。
- テスト失敗、型エラー、ビルド失敗を残したままPRを提出すること。
- 無関係な整形、依存更新、生成物を同じPRに含めること。
- `docs/inherited/` の内容を現行仕様として推測すること。

## 完了条件

- 対応する `skills/dev/` の Exit Criteria を満たしている。
- 変更範囲の検査結果と既知の未検査項目がPR説明にある。
- ドキュメント、設定、マイグレーションへの影響を確認済みである。
