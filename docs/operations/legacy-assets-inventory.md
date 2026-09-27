# 旧資産の整理一覧

この一覧は削除命令ではない。現行経路から外れていること、関連するテストと仕様の扱い、復旧可能性を確認してから一群ずつ整理する。

整理の計画・進捗は[UI改善・内部整理計画のUS-7](../plans/dots-ui-refactor-plan.md)を正本とする。この一覧は参照と処分判断だけを持つ。完了履歴はGitで追跡し、削除済みファイルを未着手候補として残さない。

## 削除候補

| 資産 | 現在の参照状況 | 扱い | 確認事項 |
| --- | --- | --- | --- |
| `src/components/LocalGoogleSignIn.*` | 現行のFounder Graph画面から参照されていない | 保留候補 | 認証境界と既存データへの影響を確認 |
| `src/components/projectDemoFixtureAdapter.js` | 現行のFounder Graphの本番経路から参照されていない可能性がある | 保留候補 | 全参照検索と画面テストを確認 |
| 完了済み個別計画、ピボット前の`docs/spec/` | 個別計画と現況正本が混在。一部はvalidatorが参照する契約を含む | 群別に集約・削除 | 契約の参照を移してから削除。古い申し送りとスマホ専用計画は削除済み、復旧はGit履歴 |
| `src/App.jsx`の`LegacyWorkspaceApp`と旧会話/料金/帳票群 | localhost:8765以外の入口と旧検査からまだ参照。現行LocalDashboardとは別経路 | 入口確認後に群別判断 | 非表示だけで未使用と断定しない。現行契約の共通処理は保持/移植し、旧入口の利用が判明した範囲だけ判断待ち |
| 旧スマホ用Story | 旧画面のStoryと混在する | 旧画面群と併せて整理 | 専用viewport/画面幅検査と計画は削除済み。共有入力保護は`src/profile-keyboard.test.jsx`へ移し、1280×720で通常検査に含める |
| 旧preview用起動手順とスクリプト | 現在は停止。別cloneの安全なUI/API確認と復旧に使う独立機能 | 維持 | 停止状態だけを未使用の根拠にしない |
| synthetic tunnel用起動手順とスクリプト | 専用WindowsタスクはDisabled、systemdはinactiveだが登録済み。master planの隔離接続受入から参照 | 契約整理まで保留 | 合成DBの安全検査と通常liveサービスを保持し、受入・復旧参照を整理してから専用起動群を処分 |

## 保護・利用確認が必要な資産

| 資産 | 理由 |
| --- | --- |
| `docs/inherited/` | 参照用資料であり、現行仕様への推測を防ぐため変更しない |
| `ModelSelector`、`HomeSupervisor`、`KnowledgeSurface`、`ProjectSurface`、PDF・DOCX adapter | 旧入口・Story・検査からの参照がある。現行localhost画面で使うことを意味しない。入口廃止と共通契約の移植可否を先に確認 |
| backendのaccount、privacy、file、decision、research、market、project dossier関連 | 公開API・検査・移行/復旧との接続を調べて群別判断。個人情報保護や現行の共通処理を古い名前だけで削除しない |

## 整理手順

1. 対象群の全文参照を確認する。
2. 現行画面、保存、検索、移行、復旧の経路に接続していないことを確認する。
3. 関連テストとStoryを残すか同じ変更で整理するか決める。
4. 既存localStorageやNeo4jデータを自動削除しないことを確認する。
5. 一群だけを削除または隔離し、基本テストとビルドを実行する。
6. 問題がなければ意味単位で記録し、次の群へ進む。

## 関連資料

- [`../plans/ci-lightening-and-legacy-disposition.md`](../plans/ci-lightening-and-legacy-disposition.md)
- [`../spikes/founder-graph-migration-inventory.md`](../spikes/founder-graph-migration-inventory.md)
