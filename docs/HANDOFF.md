# Dots. 開発申し送り

最終更新: 2026-09-22。新規作業は製品要件`docs/plans/founder-graph-pivot.md`、データ契約`docs/plans/founder-graph-data-model.md`、実行DAG`docs/plans/dots-implementation-master-plan.md`を入口とし、本書と`docs/spec/`は現状把握と移植元の確認に使ってください。

## 現在地

- 製品方針は、単独利用者向けの創業専用Founder Graphへ転換した。製品要件、8章レポート、実装フェーズ、ADRは[Dots Founder Graph ピボット・実装全体計画](plans/founder-graph-pivot.md)を正本とする。
- ノード、関係、revision、根拠の単位は[Founder Graphデータモデル正本](plans/founder-graph-data-model.md)、Luna Maxでの実行DAGと完了定義は[Dots実装全体計画](plans/dots-implementation-master-plan.md)に従う。
- PR #2のReact/Vite/Tailwind、Storybook a11y、FastAPI、uv、pytest、PR CIは`main`へマージ済みです。
- PR #3のowner-based RLS、PR #5のアイデア入力・進捗UI、PR #6の`AGENTS.md`とモデル更新方針は`main`へマージ済みです。
- Free / Standard、複数利用者、Pro、自動メールはピボット前の履歴であり、初期実装対象ではない。
- Founder Graphのkernel、in-memory read/write、MCP契約、Campaign複数Run、Source履歴、ReportVersionの永続参照validator、Luna論理model catalog、Person / Organization capture、shareable専用ResearchBrief、Neo4j parameterized gateway/read/write adapterは合成データとfake driverで検査済みです。FastAPIは安全な既定としてin-memory adapterを使い、永続経路は`create_neo4j_app`またはNeo4j read/write serviceの明示注入だけで構成します。Neo4j composition切替はQ-NGR-01と実機read/write spike後に行います。停止時はMCP `unavailable` / HTTP 503へ分類します。
- UIは既存WorkspaceのKnowledge右隣にGraphを追加し、read-only surfaceを表示できます。8章ReportVersionの差分表示とCampaign / Run比較は独立component、Graph surfaceの任意Reports tab、Appからのoptional reports prop伝播まで実装済みです。Campaign比較の実データ接続、実ファイルReport / export UI、backup / restore UIは未実装です。現行のsafe export / offline manifestが全owner backupを意味しない点は[T-FG-26 runtime監査](plans/founder-graph-t26-runtime-audit.md)と[offline backup計画](plans/founder-graph-backup-restore.md)に分離しています。Secure MCP Tunnelはnetwork-free runbook / validatorとdependency-free stdio JSON-RPC transportまでで、実tunnel接続とChatGPT tool discoveryは未検査です。Phase 6の接続前契約と実機証跡P6-E1〜E5は[Phase 6 接続前契約監査](plans/founder-graph-phase-6-contract-audit.md)に分離しています。

## 技術判断

- Frontend: React + Vite + Tailwind CSS。UIはStorybookを必須とします。
- Backend: Python + FastAPIをGraphWriteService、検索、MCPのアプリケーション境界として再利用する。
- Data: WSL2 / Docker上のNeo4j Communityを第一候補とする。Phase 0の採用スパイクが終わるまで、現行Postgresとlocal fakeを削除しない。Neo4j runtime compositionは追加済みだが、driver注入、schema migration、再起動後のwrite/read一致は未検査。
- AI: ChatGPTが会話、Deep Research、進捗・完了通知を担い、Dotsは保存、検索、構造化、provenanceへ集中する。
- Connection: privateなローカルMCPをSecure MCP Tunnelで接続できるか先行検証する。公開endpointを既定にしない。

## 開発原則

- PRは自動作成・CI確認・マージしてよい。細部の確認待ちで止まらない。
- タケさんへの確認は、製品方針の転換、外部公開、支出、契約、法務、個人情報の外部送信だけに限定します。
- 1PRは1機能。CI不合格は修正し、mainへ直接pushしません（初回リポジトリ初期化の例外は完了済み）。
- 時間駆動の無人ループは導入しない。自動化は品質ゲート付きのPR運用に限定します。

## 次の実装順序

1. Phase 0でSecure MCP Tunnel、Deep Research後のwrite-back、Neo4j実機、Luna能力、既存データ移行を合成データで検証する。2026-09-22にWindows側Docker Desktop 4.91.0 / Engine 29.8.0の応答を確認した。現在のCodex processはインストール前のPATHを保持し、Ubuntu側には`docker` CLIが未公開のため、WSL連携とNeo4j実機ゲートは未完了です。
2. Neo4jのローカル運用、schema migration、backup / restoreを構築し、offline JSON manifest / dry-runをNeo4j実機restore gateと分けたうえで、Neo4j read/write compositionをFastAPIまたはstdioへ明示注入し、再起動後のread/write一致を検証する。
3. AGENTS.md / SKILL.md、人物、組織の能力・名刺入力、名寄せ候補を実装する。Person / Organizationの基本captureとMapping/CSVのlocal normalizerは完了し、OCR・自動名寄せ・能力候補は残っています。
4. アイデア自動保存、全体検索とResearchBriefは合成データ契約まで完了。Luna logical snapshotを持つlocal-only enrichment proposal contractも追加済みで、次は実LLM推論・proposal write-backを実データ投入前のfixtureで検証する。
5. backendの固定8章impact/diff contract、safe JSON/Markdown export contract、独立ReportDiff componentをCampaign / ResearchRun比較componentへcompositionし、GraphReadPortからのbounded Campaign comparison adapterとdependency-free stdio JSON-RPC transportを追加した。残りは実データ接続、8章ReportVersionの差分・訂正UIのruntime配線、backup / restore / delete UI、Secure MCP Tunnelの実機gateである。
6. ChatGPT Deep Research、通知、通常チャットwrite-backを実機接続する。外部AI接続と実データ送信は明示決裁境界を通し、P6-E1〜E5をredacted metadataで記録する。
7. backup / restore、削除、Markdown / JSON exportとthreat modelを確認後、旧Postgres / local fakeを移行またはread-only化する。

## 仕様の核

- [Dots Founder Graph ピボット・実装全体計画](plans/founder-graph-pivot.md)
- [PRD v0.2（ピボット前の履歴）](spec/PRD.md)
- [アーキテクチャ v0.2（ピボット前の履歴）](spec/architecture.md)
- [仮説検証・調査支援仕様（移植元）](spec/falsification-engine.md)
- [実装バックログ（ピボット前の履歴）](spec/backlog.md)
- [横断調査・個人ナレッジ・意思決定記憶 計画（移植元）](spec/research-memory-plan.md)
- [事業のタネの既存入力契約（移植元）](spec/business-seed-plan.md)

## 注意事項

- `docs/inherited/ai-company-os`と`docs/inherited/mba-practice-app`はサブモジュールです。継承元の作業ツリーを改変しないでください。
- MBA由来のGROWTH_PATTERNS/LESSONSはサブモジュール配下に追跡できないため、必要ならDots.本体の`docs/inherited-reports/`へ移します。
- Xは`x-drafts/`への下書きのみ。投稿APIや自動投稿を実装しません。
