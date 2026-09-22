# 旧資産の整理一覧

最終更新: 2026-09-23

この一覧は削除命令ではない。現行経路から外れていること、関連するテストと仕様の扱い、復旧可能性を確認してから一群ずつ整理する。

## 削除候補

| 資産 | 現在の参照状況 | 扱い | 確認事項 |
| --- | --- | --- | --- |
| `src/components/IdeaCandidateWorkspace.*` | 現行のFounder Graph画面から参照されていない。自身のテスト・Storyが中心 | 保留候補 | 関連テスト・Storyを同時に整理できるか確認 |
| `src/components/IdeaForm.*` | 現行のFounder Graph画面から参照されていない。自身のテスト・Storyが中心 | 保留候補 | 保存経路とlocalStorage移行資料への参照がないか確認 |
| `src/components/ResearchWorkspace.*` | 現行のFounder Graph画面から参照されていない。自身のテスト・Storyが中心 | 保留候補 | ResearchCampaign移行との関係を確認 |
| `src/components/FileLibrary.*` | 現行のFounder Graph画面から参照されていない。自身のテスト・Storyが中心 | 保留候補 | Attachment移行との関係を確認 |
| `src/components/LocalGoogleSignIn.*` | 現行のFounder Graph画面から参照されていない | 保留候補 | 認証境界と既存データへの影響を確認 |
| `src/adapters/projectDemoFixtureAdapter.js` | 現行のFounder Graphの本番経路から参照されていない可能性がある | 保留候補 | 全参照検索と画面テストを確認 |

## 削除しない資産

| 資産 | 理由 |
| --- | --- |
| `docs/inherited/` | 参照用資料であり、現行仕様への推測を防ぐため変更しない |
| `src/components/ModelSelector.*` | 移行判断まで既存のモデル選択UIを削除しない方針がある |
| `HomeSupervisor`、`KnowledgeSurface`、`ProjectSurface` | 現行画面またはデータ経路から参照されている |
| PDF・DOCX adapter | 現行画面または出力確認から参照されている |
| backendのaccount、privacy、file、decision、research、market、project dossier関連 | 現行API、テスト、移行契約、削除・復旧計画から参照されている |

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
