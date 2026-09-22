# SP-FG-03 Founder Graph 移行インベントリ

最終検証日: 2026-09-20

## 判定要約

本書は、[Founder Graph ピボット計画](../plans/founder-graph-pivot.md) の SP-FG-03 に対する静的インベントリである。対象checkoutには実Supabase/Postgres接続、実ユーザーデータ、ブラウザのlocalStorage実体は存在しないため、ここで記録する件数はリポジトリ内のスキーマ、コード、合成fixture、テストの件数であり、本番データ件数ではない。

- Supabase migrationは5本、15テーブル、1 view、3 enumを定義する。旧Postgresを新グラフの正本にしない。
- FastAPI、純粋な取込・計算・privacy契約、owner境界、Evidenceのlocator/hash、export adapterは再利用候補として保持する。
- local fake、ブラウザ保存、5観点UI、Dots内蔵research executor、Free / Standard / billingは、Founder Graphの契約へ変換するまで正本にしない。移行中は read-only または合成fixture専用で残す。
- Postgres/local fakeの削除、旧料金・認証・内蔵調査UIの撤去は、Q-FG-03の決定と Phase 1〜7、特に backup / restore・delete・export の Gate D 通過後だけにする。
- dual-writeは行わない。変換中は旧系をread-onlyに固定し、失敗一覧と入力snapshotから再実行する。

### 分類

| 分類 | 意味 |
| --- | --- |
| `keep` | 契約、純粋ロジック、UI骨格、テストを新境界の下位部品として保持する。データ正本は移さない。 |
| `adapt` | GraphWriteService、Graph read、MCP、OwnerProfile、revision / provenanceに合わせて入力・保存先・表示を変える。 |
| `archive` | JSON/exportまたはread-only参照として旧形式を保存する。新しいwrite先にはしない。 |
| `retire` | Founder Graphの初期責務外であり、移行・parity確認後に撤去する。 |

## SP-FG-03の受入条件

### US-SP-FG-03-1: 既存成果物を追跡する

As a 移行担当者, I want 既存のschema、backend、frontend、fake、export、research、testsを証拠付きで分類したい, so that 移行漏れと二重正本を防げる。

Given: このcheckoutの既存ファイルと合成fixtureがある

When: 本書のインベントリ表を確認する

Then: 各対象に `keep`、`adapt`、`archive`、`retire` のいずれかとFounder Graphの対応先がある。

### US-SP-FG-03-2: 旧データを失わずに判定する

As a 単独利用者, I want 移行前の件数、JSON export、hash、失敗一覧、rollback対象を保存したい, so that Q-FG-03の移行またはread-only保持を選べる。

Given: 旧Postgresまたは端末内保存データを移行する直前である

When: export、dump、件数照合、変換を実行する

Then: 旧正本は削除されず、入力snapshotと変換結果を同一世代で再照合できる。

### US-SP-FG-03-3: 外部送信境界を保つ

As a 単独利用者, I want private fieldとlocal-onlyデータをLuna、Web、ChatGPTへ渡さない状態で移行したい, so that 移行が情報流出経路にならない。

Given: profile、Person、連絡先、非公開メモ、合成fixture、research evidenceが混在している

When: Graph projection、ResearchBrief、exportを生成する

Then: `local_only` は外部projectionに0件で、合成fixtureは `synthetic_demo` として実データと区別される。

## 静的観測と件数

| 対象 | 観測結果 | 証拠 |
| --- | --- | --- |
| Supabase migration | 5ファイル、15 tables、1 view、3 enum。`owner_id`、RLS、cascadeを含む。 | [`supabase/migrations`](../../supabase/migrations) |
| backend | `backend/dots` のlegacy baselineに16 Python module。FastAPIの入口、local fake、research、ingestion、計算、exportを含む。 | [`backend/dots`](../../backend/dots) |
| frontend | React/Vite、Home / Project / Knowledgeの3 surface、localStorage repository群、Storybook/テスト。 | [`src/App.jsx`](../../src/App.jsx)、[`src/components`](../../src/components) |
| 合成backend fixture | admin datasetはmessages 3、sections 5、competitors 3、knowledge assets 5、decisions 1。 | [`backend/dots/admin_demo_dataset.py`](../../backend/dots/admin_demo_dataset.py) |
| 合成frontend fixture | asset 1、project 1、decision 1。 | [`src/fixtures/knowledge-admin-demo.json`](../../src/fixtures/knowledge-admin-demo.json) |
| runtime data | 実DB、Supabase、localStorageの実体は未接続・未読取。実ユーザー件数は未確定。 | [`docs/HANDOFF.md`](../HANDOFF.md)、[`AGENTS.md`](../../AGENTS.md) |

## 1. Supabase / Postgres schema

旧schemaの `owner_id` は新Graphの `OwnerProfile.id` へ直接流用せず、`legacy_owner_id` として移行manifestに残す。旧UUID、ブラウザの文字列ID、合成IDは namespace を分ける。

| 旧対象 | Founder Graphへの対応 | 分類 | 移行上の注意 |
| --- | --- | --- | --- |
| `dots_ideas` (`001`) / `title`, `idea_summary` (`002`) | `Idea` の現行revision。`pain_statement` は `Source` / `SourceRevision` と `Claim` の原文根拠にもする。 | `adapt` | `draft`等のstage enumをそのまま新core typeにしない。旧IDをlegacy locatorとして保持する。 |
| `dots_stage_runs` (`001`) | `Experiment` または検証Run。`stage`, `actor_role`, `artifact`, status、execution_idを provenance とともに保存する。 | `adapt` | stage runはIdeaの直接上書きではなく、結果ClaimとEvidenceへ分解する。 |
| `dots_death_causes` (`001`) | 失敗学習の `Claim` / `Evidence`。`source_url` は `SourceRevision.locator` へ変換する。 | `adapt` | cascadeで消えた過去データは復元不能。現存行だけを変換し、失敗一覧へ記録する。 |
| `dots_decision_records` (`001`) | `Decision` と `Claim` / `Evidence`。後継判断は `SUPERSEDES`、状態は active/expiredからrevisionへ変換する。 | `adapt` | category `a`〜`e` は新しい本人判断・DecisionCriterionへ意味付けしてから変換する。 |
| `dots_consents` (`001`) | `OwnerProfile` の外部送信設定、および `ResearchCampaign` の許諾snapshotへ分離する。 | `adapt` | `anonymized_statistics_opt_in` は初期Founder Graphの許諾契約へ自動移植しない。withdrawnを失わない。 |
| `dots_deletion_requests` (`001`) | Graph delete commandの監査event。物理削除ではなくsoft delete、hash、日時、影響範囲を記録する。 | `adapt` | 旧enumのcompletedを新しい削除伝播の完了とはみなさない。attachments、chunks、projectionの確認が必要。 |
| `dots_source_documents` (`003`) | `Source`。source_type、title、state、current revision、ownerを保持する。 | `adapt` | file / web / manualをSource Artifactへ正規化し、private policy未設定はlocal_onlyにする。 |
| `dots_document_versions` (`003`) | `SourceRevision` とcontent-addressed `Attachment` metadata。storage_path、mime、hash、versionを移す。 | `adapt` | 実本文をGraph nodeへ詰め込まず、pathとhashを分離する。旧pathの存在確認なしにreadyへしない。 |
| `dots_document_chunks` (`003`) | `Evidence` の抽出locaterとfull-text index入力。page、chunk_index、content hashを保持する。 | `adapt` | `deleted`、非current version、別ownerを検索結果へ混ぜない。Neo4j full-text parityを確認する。 |
| `dots_research_runs` (`003`) | `ResearchCampaign` 配下の不変 `ResearchRun`。model_snapshot、selected_sources、statusをinput snapshotと一緒に保存する。 | `adapt` | 旧runはidea直結・更新可能。方針変更の再試行は新Run、通信retryだけ同一Runに限定する。 |
| `dots_research_evidence` (`003`) | `Evidence` と `SourceRevision` の関係。locator、excerpt、fetched_at、content_hashを保持する。 | `adapt` | web/patent/document/decisionをcore typeへ昇格しない。根拠の分類と外部送信許諾を別fieldにする。 |
| `dots_decision_observations` (`003`) | `Decision` に紐づく `Claim` / Evidence observation。dispositionは状態付きassertionへ変換する。 | `adapt` | `evidence_id`が欠ける観測は未確認として隔離し、事実にしない。 |
| `dots_document_chunk_embeddings` (`004`) | Graph検索の補助index metadata。embedding JSONを canonical knowledge として移さず、対応能力評価後に再計算する。 | `archive` | pgvector未導入、adapter_nameごとに次元保証なし。SP-FG-04未達なら graph + full-text + Luna rerankへ延期する。 |
| `dots_project_knowledge` (`005`) | `Asset` / `Claim` と `Idea` 間の再利用関係。anonymized_content、source_id、削除状態を保持する。 | `adapt` | raw customer interviewを取り込まず、匿名化済み派生物と根拠を分離する。 |
| `dots_knowledge_grants` (`005`) | relation assertionの状態（proposed/active/revoked）へ変換する。 | `archive` | 同一owner spaceの既定参照と旧project grantは意味が違う。互換readを先に置き、grantを即削除しない。 |
| `dots_active_project_knowledge` view (`005`) | 安全な旧read projectionとしてparity確認に利用する。 | `archive` → `retire` | Graph read surfaceが同じowner/deletion semanticsを返すまで撤去しない。 |
| `dots_idea_status`, `dots_stage_run_status`, `dots_deletion_request_status` | legacy enumをmigration manifestの変換元として保存する。Graphの自由な型追加には使わない。 | `archive` | core node/relation allowlistを増やす入力にしない。 |

## 2. Backend / local fake / domain logic

| 既存ファイル | 観測された契約 | Founder Graphでの扱い |
| --- | --- | --- |
| [`backend/dots/main.py`](../../backend/dots/main.py) | `/v1/account/export`、deletion、research-runs、decision、market-report、project-knowledgeをlocal repositoryへ委譲。owner headerと明示的なHTTP errorを持つ。 | `adapt`: FastAPIを唯一のGraphWriteService / search boundaryとして残し、MCP read/write surfaceは同じdomain serviceへ委譲する。旧routeはcompatibility read期間だけ保持する。 |
| [`backend/dots/runtime.py`](../../backend/dots/runtime.py) | `FakeRuntime`はnetworkなし、owner isolation、timeout/limit/deleteを再現。`UnconfiguredRuntime`はproduction未設定を503にする。 | `keep` + `adapt`: unavailable/停止時の明示契約をGraph DB、MCP tunnelへ適用する。billing、汎用AI、外部web portは初期scopeから外す。 |
| [`backend/dots/account_privacy.py`](../../backend/dots/account_privacy.py) | ownerごとのJSON/Markdown exportと全artifact deletion manifest。 | `adapt`: OwnerProfile、Idea、Asset、Source、Run、Decision、ReportVersionと、original/extracted/chunks/embeddingsの全派生物へ拡張する。 |
| [`backend/dots/file_ingestion.py`](../../backend/dots/file_ingestion.py) | PDF/DOCX/TXT/CSVの署名・サイズ・暗号化・macro/script判定、page hash、4種削除manifest。 | `keep` + `adapt`: SourceRevision/Attachment intakeの純粋validatorとして保持。保存・OCR・外部送信はGraph境界の外へ出さない。 |
| [`backend/dots/space_knowledge.py`](../../backend/dots/space_knowledge.py) | 固定owner、content hash dedupe、reference metadata、削除伝播、local fake embedding。 | `adapt`: Source/Asset/Claimとcontext relationへ写像する。hash dedupeとreference unavailable契約は維持し、fake embeddingは本番正本にしない。 |
| [`backend/dots/project_knowledge.py`](../../backend/dots/project_knowledge.py) | owner-scoped anonymized knowledge、grant/revoke/delete、active candidates。 | `adapt`: AssetとIdea/Claimの関係候補へ移す。revoked/deletedを現行検索から除外し、旧grantはread-only compatibilityへ。 |
| [`backend/dots/decision_memory.py`](../../backend/dots/decision_memory.py) | owner + idea単位のDecision、observations、supersedes、active/expired search。 | `adapt`: `Decision`、`Claim`、`Evidence`へ分離し、`SUPERSEDES` と revision provenanceを必須にする。idea_idだけに閉じない。 |
| [`backend/dots/hybrid_search.py`](../../backend/dots/hybrid_search.py) | owner/deleted/current boundary後にkeyword/semantic RRF。`DeterministicFakeEmbeddingAdapter`は語の集合をvector代用。 | `keep` + `adapt`: graph traversal + full-text + Luna rerankの評価ハーネスへ。fake vectorを実embeddingと表示しない。 |
| [`backend/dots/research_orchestrator.py`](../../backend/dots/research_orchestrator.py) | 選択source、partial、timeout、daily limit、failed sourceだけretry、owner read isolation。 | `archive` + `adapt`: 状態/部分成功のテスト契約はResearchRunへ移すが、Dots内の調査実行・通知は初期責務から外す。Deep ResearchはChatGPT側。 |
| [`backend/dots/research.py`](../../backend/dots/research.py) | Web/JPO adapter protocol、特許番号正規化、Evidence化、partial error、fake sources。 | `keep` + `adapt`: locator/normalization/Evidence fixtureを保存契約へ使う。実Web/JPO clientやcredentialをこの移行で追加しない。 |
| [`backend/dots/market_report.py`](../../backend/dots/market_report.py) | evidence分類、競合3種、potential entrant、owner judgment、card update。 | `adapt`: 8章ReportVersionの2〜4章とClaim/Evidence/Decisionへ分割する。mutable card approvalは不変ReportVersion + 新Decisionへ置き換える。 |
| [`backend/dots/project_dossier.py`](../../backend/dots/project_dossier.py) | 5観点、根拠、AI推論、本人判断、missing/freshnessを決定的にassemble。 | `adapt` + `archive`: Evidence分離と未確認表示は維持し、5観点は8章adapterの入力にする。`ProjectDossier`を最終レポートschemaにしない。 |
| [`backend/dots/unit_economics.py`](../../backend/dots/unit_economics.py) | Decimal、通貨、base/upside/downside、CAC/LTV、break-even、operating profit。 | `keep` + `adapt`: ReportVersion 3章、DecisionCriterion、Experimentの決定的計算へ。結果に式・単位・期間・通貨を添える。 |
| [`backend/dots/execution_plan.py`](../../backend/dots/execution_plan.py) | 時間/家計資金上限、可逆experiment、撤退条件、resource/roadmap。 | `keep` + `adapt`: `Experiment` とReportVersion 5〜7章の入力へ。金融・法務・融資判断の自動化は持ち込まない。 |
| [`backend/dots/formal_plan_export.py`](../../backend/dots/formal_plan_export.py) | owner一致を確認し、計算/取得なしでDOCXを生成。locator、AI推論、本人判断、未確認理由を出力。 | `adapt`: `ReportVersion` 8章のMarkdown/JSON/DOCX/PDF adapterへ。raw private field、owner ID、未確認の隠蔽を禁止する。 |
| [`backend/dots/admin_demo_dataset.py`](../../backend/dots/admin_demo_dataset.py) | `synthetic_demo` provenance、参照整合、財務計算整合をvalidatorで保証。 | `keep`: 合成fixture専用。Graph import時も `synthetic_demo` を付け、実OwnerProfile・実Reportと混ぜない。 |

## 3. Frontend / localStorage / UI

| 既存対象 | 観測された保存・表示 | Founder Graphでの扱い |
| --- | --- | --- |
| [`src/App.jsx`](../../src/App.jsx) + [`WorkspaceShell.jsx`](../../src/components/WorkspaceShell.jsx) | Home / Project / Knowledge、profile hydration、adopted project、portfolio、settings/planをlocal repositoryへ接続。 | `adapt`: Ideas / Assets / Sources / People / ReportVersionの最小閲覧・訂正・履歴UIへ。Graph unavailableを画面状態として表示し、Appとshared styleを別PRで扱う。 |
| [`HomeSupervisor.jsx`](../../src/components/HomeSupervisor.jsx) + [`homeConversationRepository.js`](../../src/components/homeConversationRepository.js) | 会話、draft、proposal、adopt/hold/reject、owner/space scoped key、quarantine。 | `adapt`: `capture_idea`入力とIdea revisionのUI/adapterへ。原文、候補、生成主体、時刻、idempotencyをGraphへ渡す。 |
| [`IdeaCandidateWorkspace.jsx`](../../src/components/IdeaCandidateWorkspace.jsx) | legacy keys `dots:idea-candidates`、`dots:idea-conversation`、`dots:idea-input-draft`、`dots:idea-form-draft`。明示採用時だけprojectへ昇格。Appの現行入口ではない。 | `archive`: 初回Graph画面へ自動確定移行しない。read-only import候補として保持し、利用者の明示操作後にSource/Idea revisionへ変換する。 |
| [`adoptedProjectRepository.js`](../../src/components/adoptedProjectRepository.js) + [`projectConversationRepository.js`](../../src/components/projectConversationRepository.js) | owner/space/project scoped conversation、draft、quarantine、F5復元。 | `adapt`: Idea/Project viewのGraph ID + revision参照へ。local snapshotはcache/rollback用で、canonical dataにしない。 |
| [`ProjectSurface.jsx`](../../src/components/ProjectSurface.jsx) + `ProjectEvaluationTabs.jsx` | 5観点、会話、DOCX/PDF download、legacy「利益はでる」互換表示。 | `adapt`: 8章 ReportVersion、Run比較、Claim区分、citation、訂正へ。5観点の見出しを新契約の最終表示に残さない。 |
| [`KnowledgeSurface.jsx`](../../src/components/KnowledgeSurface.jsx) + [`knowledgeMetadataRepository.js`](../../src/components/knowledgeMetadataRepository.js) | file metadata、version/state、owner/space scoped envelope、tombstone、quarantine、decision/note/profile entries。 | `adapt`: Assets / Sources / People一覧とSourceRevision詳細へ。外部送信用projectionをlocal全体検索から分離する。 |
| [`knowledgeConversationRepository.js`](../../src/components/knowledgeConversationRepository.js) | Knowledge conversation/entries、category、sourceType、confidence、unknowns、project evidence locator。 | `adapt`: Claim/Evidence/Decisionの閲覧・訂正・provenanceへ。raw conversationはlocal_only、保存原文の外部投影は禁止。 |
| [`FileLibrary.jsx`](../../src/components/FileLibrary.jsx) | PDF/DOCX/TXT/CSV、25 MiB、processing/searchable/failed/deleted、fake add/retry/version/delete。 | `adapt`: backend `file_ingestion` + SourceRevision/Attachmentへ。削除確認はoriginal/extracted/chunks/embeddingsのmanifest完了までdeleted表示にしない。 |
| [`ResearchWorkspace.jsx`](../../src/components/ResearchWorkspace.jsx) | Web/JPO/file/decisionのlocal fake、partial結果、locator、failed source retry。Appの現行入口ではない。 | `retire` UI executor; `adapt` status/evidence rendering into Campaign/Run/ReportVersion UI. Dots独自research job・notificationを復活させない。 |
| [`formalPlanPdfAdapter.js`](../../src/components/formalPlanPdfAdapter.js) + [`formalPlanDocxAdapter.js`](../../src/components/formalPlanDocxAdapter.js) | `project.sections`を走査し、ローカルBlobをdownload。未確定と注意書きを出す。 | `adapt`: 同一ReportVersion中間契約から8章のPDF/DOCXを作る。adapterはGraph取得・計算・owner認証をしない。 |
| [`projectDemoFixtureAdapter.js`](../../src/components/projectDemoFixtureAdapter.js) + `knowledge-admin-demo.json` | PII-free synthetic project、5観点、3 decisions、1 asset/project/decision。 | `keep` as fixture; 8章/Graph fixtureへ変換するまで実データ経路に接続しない。 |
| [`contextSnapshot.js`](../../src/context/contextSnapshot.js) | owner、visible permission、deleted/hidden除外、entity ID/name/locator/revision、fact/inference allowlist。 | `adapt`: selected entityをIdea/Asset/Person/Source/Decisionへ更新し、ResearchBrief用shareable projectionとlocal snapshotを分離する。 |
| [`UserProfileInterview.jsx`](../../src/components/UserProfileInterview.jsx) | 端末内プロフィール入力、途中再開、completed状態。 | `adapt`: `OwnerProfile` の制約・時間・資金・判断傾向へ。Personのprivate contactと同じprojectionへ混ぜない。 |
| [`localAuthAdapter.js`](../../src/auth/localAuthAdapter.js) + `LocalGoogleSignIn.jsx` | `google-local-mock` principalをversioned localStorageへ保存。 | `adapt`: 単独利用者のlocal principal境界として保持し、外部OAuth・multi-user・provider表示を初期Graphへ移さない。 |
| [`sidebarPortfolioRepository.js`](../../src/components/sidebarPortfolioRepository.js) | Home/Project/Knowledge履歴、archive/restore/unread、owner/space scoped key。 | `keep` + `adapt`: Graph ID/revisionを参照するUI index。正本はGraphであり、snapshotはrollback用。 |
| [`planSubscriptionRepository.js`](../../src/components/planSubscriptionRepository.js)、`PlanSelection.jsx`、`ModelSelector.jsx` | Free / Standard、local plan storage、reasoning mode、旧Anthropic/Terra catalog。 | `retire` plan/billing UI and storage; `adapt` model catalog to one logical Luna capability key via provider adapter. Existing model choicesは移行判断まで削除しない。 |

## 4. Tests / fixtures / docs

| 既存対象 | 観測された検証 | Founder Graphでの扱い |
| --- | --- | --- |
| [`backend/tests/test_supabase_schema.py`](../../backend/tests/test_supabase_schema.py)、[`test_idea_definition_migration.py`](../../backend/tests/test_idea_definition_migration.py)、[`test_research_memory_migration.py`](../../backend/tests/test_research_memory_migration.py)、[`test_hybrid_search_migration.py`](../../backend/tests/test_hybrid_search_migration.py)、[`test_project_knowledge_migration.py`](../../backend/tests/test_project_knowledge_migration.py) | RLS、owner複合FK、grant、embedding JSON、全文検索function、既存decision維持をmigration本文から確認。 | `keep` as legacy regression until archive; add equivalent Graph schema/restore tests before retiring SQL. |
| [`backend/tests/test_account_privacy_api.py`](../../backend/tests/test_account_privacy_api.py)、`test_file_ingestion.py`、`test_space_knowledge.py` | export/deletion、4種manifest、hash dedupe、reference削除伝播、owner境界。 | `keep` contract; extend fixture to 15 core nodes, attachment, soft-delete, hash-only past report. |
| [`backend/tests/test_research_orchestrator.py`](../../backend/tests/test_research_orchestrator.py)、`test_patent_research_contract.py`、`test_hybrid_search.py` | partial/timeout/limit/retry、JPO normalization、RRF、deleted/current/owner filter。 | `adapt` to immutable Campaign/Run/Evidence and Luna capability evaluation; no external call in Phase 0. |
| [`backend/tests/test_decision_memory_api.py`](../../backend/tests/test_decision_memory_api.py)、`test_market_report_api.py`、`test_project_dossier_api.py`、`test_unit_economics.py`、`test_execution_plan.py` | supersedes、evidence分類、5観点、Decimal計算、可逆experiment。 | `adapt` tests to Claim/Evidence/DecisionCriterion and 8 chapters; preserve deterministic calculation assertions. |
| [`backend/tests/test_runtime_parity.py`](../../backend/tests/test_runtime_parity.py)、`test_health.py` | fake/unconfigured status、unavailable、timeout、limit、delete。 | `keep` and add Neo4j/MCP stopped-state tests for US-FG-08. |
| frontend repository tests (`homeConversationRepository.test.js`, `knowledge*Repository.test.js`, `projectConversationRepository.test.js`, `sidebarPortfolioRepository.test.js`) | scoped key、legacy copy、quarantine、write-block、retry、F5、削除tombstone。 | `keep` as local adapter regression; add Graph adapter tests and never replace corrupt raw data automatically. |
| frontend UI/E2E/Storybook tests (`App*`, `HomeSupervisor`, `KnowledgeSurface`, `ProjectSurface`, `ResearchWorkspace`, `ui-e2e-quality`) | 3 surface、keyboard/a11y、owner/space、no network、decision UI、export status。 | `adapt` acceptance to minimal Ideas/Assets/Sources/People and unavailable/empty states; synthetic fixture remains non-production. |
| [`docs/spec/research-memory-plan.md`](../spec/research-memory-plan.md)、[`docs/plans/issue-68-formal-business-plan-export.md`](../plans/issue-68-formal-business-plan-export.md) | Evidence、削除伝播、5観点、DOCX/PDF adapter/privacyの移植元。 | `keep` as historical contract; Founder Graphの8章、Campaign/Run、MCP境界を優先する。 |

## 5. 移行順序と停止条件

1. **Freeze / baseline** — 旧Postgresへのwriteを短いfreeze windowで停止し、削除はせず、DB schema version、tableごとのrow count、JSON/Markdown export、dump hash、localStorage raw、fixture hashを取得する。実データがない場合は `not observed` と記録する。
2. **Legacy manifest** — 旧IDを `legacy:<source>:<id>` へnamespaceし、owner mapping、source locator、content hash、revision候補、削除状態、失敗理由をCSV/JSON manifestへ固定する。request bodyのownerを信頼しない。
3. **Canonical source first** — OwnerProfile、InstructionArtifact、Source、SourceRevision、Attachment metadataを先に作る。pathが存在しない、hash不一致、private policy不明の入力はlocal_only / failedへ隔離する。
4. **Ideas / Assets / People** — `dots_ideas`、local Home/proposal、knowledge metadataをIdea/Asset/Person/Organizationへ変換し、原文をSourceRevision、抽出をClaim、関係候補をproposed/inferredへ分離する。自動名寄せはSP-FG-04通過後だけ。
5. **Evidence / Decisions / Experiments** — chunks、death causes、decision records/observations、stage runsをClaim/Evidence/Decision/Experimentへ変換する。旧更新可能レコードは新revisionへ展開し、旧値を消さない。
6. **Campaign / Run / ReportVersion** — research runs/evidence、market report、project dossier、unit economics、execution planを複数不変Runと8章ReportVersionへ変換する。Dots内蔵executorは変換後も起動しない。
7. **Graph validation** — 合成20会話、合成10名刺相当、代表10問、2 Run比較、delete/export/restoreで、node/relation件数、provenance、owner、projection、失敗一覧を照合する。Gate A/B/C未達なら実データを入れない。
8. **Read switch** — Graph readが同じまたは明示的に変換された結果を返し、MCP unavailable、private projection、soft delete、ReportVersion差分が通った後に読み取りを切り替える。旧Postgres/local fakeはread-only archiveにする。
9. **Retirement** — Gate D（backup / restore、delete、export）が実データfixtureで通り、Q-FG-03が決まった後にだけ、旧料金/認証/内蔵research UI、compatibility view、不要なSupabase writeを撤去する。旧snapshotとrollback手順は保管する。

### Rollback

- 変換前のJSON export、Postgres dump、table counts、hash、legacy manifestを世代付きで保持する。
- Graph write feature flagを停止し、旧read-only archiveまたは直前Graph dumpへ戻す。dual-writeの不整合を後から推測して直さない。
- 失敗行、missing source、hash mismatch、relation候補の隔離一覧を残し、同じ入力snapshotで再実行する。
- ReportVersion / ResearchRunは削除せず `invalidated` と理由を追記する。削除済みSourceは現行検索から除外し、過去reportには参照不能表示、hash、日時だけを残す。

## 6. データリスクと軽減策

| リスク | 軽減策 / 停止条件 |
| --- | --- |
| Postgres UUID、localStorage文字列、合成IDの衝突 | namespace付きlegacy IDとOwnerProfile mappingを使う。衝突が解消するまで変換を停止する。 |
| 旧cascade / 物理deleteで履歴が欠落 | 現存snapshotのみ変換し、削除行は件数・hash・削除日時の証跡だけを記録。Gate D前に旧DBを消さない。 |
| 旧`owner_id`と単独local principalの意味差 | `legacy_owner_id`を監査へ残し、canonical ownerは固定されたlocal OwnerProfileから解決する。body/headerの任意ownerを正本にしない。 |
| revision/provenance不足 | 変換単位にsource ID、actor、model/rule snapshot、prompt/rule version、occurred_at、idempotency keyを付与。欠落はunconfirmedへ隔離する。 |
| private contact / profileの外部流出 | policy未設定をlocal_only、通常MCPはshareableのみ、ResearchBriefは許諾済みClaimだけにする。悪性Web fixtureで0件を確認する。 |
| `dots_document_chunk_embeddings`のfake/次元不一致 | embedding JSONをcanonicalにしない。SP-FG-04未達時はgraph + full-text + Luna rerank、未承認provider追加なし。 |
| old research retryの同一Run上書き | transport retryと方針変更を区別し、後者は新Run + 新ReportVersionへ変換する。 |
| project grantとsame-space default reuseの混同 | 旧grantはrevoked/deletedを保持した互換readに限定し、Graph relation parity後にviewをretireする。 |
| demo fixtureと実データの混在 | `synthetic_demo`、dataset ID、generated_onを必須にし、実OwnerProfileへimportしない。 |
| exportが旧5観点、owner ID、raw本文を漏らす | ReportVersionの8章中間契約を先に検証し、adapterは取得・計算・認証をしない。出力read-backとprivate scanを行う。 |
| 旧Free/Standard、mock Google、billingが製品境界へ残る | plan storage/UIをretire対象にし、model catalogはLuna logical keyのprovider adapterだけへ縮小する。 |

## 7. 完了チェックリスト

- [ ] 15 tables、1 view、3 enum、5 migrationの全対象に対応先と分類がある。
- [ ] backend legacy baseline 16 modules、現行3 surface、localStorage repositories、research/export UI、tests/fixturesを本書で追跡できる。
- [ ] 実データ未接続を明示し、runtime row countを推測していない。
- [ ] OwnerProfile、Source/SourceRevision、Claim/Evidence、Idea/Asset/Person、Decision/Experiment、Campaign/Run/ReportVersionへの写像がある。
- [ ] legacy ID namespace、owner mapping、content hash、revision/provenance、soft-deleteをmanifestで固定する計画がある。
- [ ] Graph schema/read/writeとMCPのGate A/B/C、backup/restore/delete/exportのGate D前に旧Postgresを削除しない。
- [ ] local fakeとブラウザstateはread-only/adapterとして保持し、dual-writeを行わない。
- [ ] private/local_only、synthetic_demo、embedding非対応、partial retry、grant revoke、export漏えいのリスクと停止条件がある。
- [ ] Q-FG-03（Graph変換かJSON export後のread-only保持）が利用者決定待ちとして残っている。
- [ ] 下記の静的検査、相対リンク検査、`git diff --check` が通っている。

## 実行したコマンド

作業開始時の確認（すべてread-only）:

```powershell
Get-Content -LiteralPath 'AGENTS.md' -Encoding UTF8
Get-Content -LiteralPath 'skills\dev\INDEX.md' -Encoding UTF8
Get-Content -LiteralPath 'skills\dev\planning\SKILL.md' -Encoding UTF8
Get-Content -LiteralPath 'skills\dev\implementation\SKILL.md' -Encoding UTF8
Get-Content -LiteralPath 'docs\operations\department-handoffs.md' -Encoding UTF8
Get-Content -LiteralPath 'docs\plans\founder-graph-pivot.md' -Encoding UTF8
git status --short
```

インベントリ観測:

```powershell
rg --files -g '!node_modules' -g '!dist' -g '!build'
Get-ChildItem -LiteralPath 'backend\dots' -File | Select-Object Name,Length
Get-ChildItem -LiteralPath 'backend\tests' -File | Sort-Object Name | Select-Object Name,Length
Get-ChildItem -LiteralPath 'supabase\migrations' -File | Sort-Object Name | Select-Object Name,Length
rg -n -i 'create table|create view|create type|owner_id|embedding|research|decision|project_knowledge' supabase\migrations -g '*.sql'
rg -n '^(def test_|async def test_)' backend\tests -g '*.py'
rg -n 'dots:[A-Za-z0-9:_-]+' src -g '*.js' -g '*.jsx' -g '!*.test.*' -g '!*.stories.*'
rg -n 'ResearchWorkspace|FileLibrary|IdeaCandidateWorkspace|PlanSelection|ModelSelector|formalPlan|download' src -g '*.jsx' -g '*.js' -g '!*.test.*' -g '!*.stories.*'
```

本書作成後の検査:

```powershell
git diff --check -- docs/spikes/founder-graph-migration-inventory.md
rg -n '^## |SP-FG-03|Q-FG-03|keep|adapt|archive|retire|Rollback|完了チェックリスト' docs/spikes/founder-graph-migration-inventory.md
python -X utf8 -c "from pathlib import Path; import re; p=Path(r'docs/spikes/founder-graph-migration-inventory.md'); s=p.read_text(encoding='utf-8'); links=re.findall(r'\]\(([^)]+)\)', s); root=p.parent; bad=[(link, str((root / link).resolve())) for link in links if not link.startswith(('http://','https://','#','mailto:')) and not (root / link).exists()]; print(f'links={len(links)} bad={len(bad)}'); print('\\n'.join(f'{link} -> {target}' for link,target in bad)); raise SystemExit(1 if bad else 0)"
python -X utf8 -c "from pathlib import Path; p=Path(r'docs/spikes/founder-graph-migration-inventory.md'); s=p.read_text(encoding='utf-8'); print('utf8=PASS replacement_chars=', s.count(chr(0xfffd))); print('headings=', s.count('## '), 'acceptance_then=', s.count('Then'+chr(58)), 'tables=', s.count('| --- |')); assert chr(0xfffd) not in s; assert s.count('Then'+chr(58)) == 3; assert s.endswith('。'+chr(10)) and not s.endswith('。'+chr(10)*2)"
python -X utf8 -c "from pathlib import Path; p=Path(r'docs/spikes/founder-graph-migration-inventory.md'); lines=p.read_text(encoding='utf-8').splitlines(); bad=[i for i,line in enumerate(lines,1) if line.endswith((' ',chr(9)))]; raw=p.read_bytes(); eol=len(raw)-len(raw.rstrip(bytes([13,10]))); print(f'trailing_whitespace_lines={bad} eof_newlines={eol}'); assert not bad; assert eol == 1"
git diff --no-index --check -- 'NUL' 'docs/spikes/founder-graph-migration-inventory.md'
```

`skills/dev/docs-freshness/SKILL.md` はこのcheckoutに存在しなかったため、INDEXの常時適用規則に代えて、相対リンク存在確認と本文の最終検査を実行した。外部サービス、Supabase、Neo4j、MCP tunnel、実ユーザーデータには接続していない。
