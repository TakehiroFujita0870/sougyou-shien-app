# Dots Founder Graph ピボット・実装全体計画

最終検証日: 2026-09-22

## 正本の位置づけ

本書は、Dotsを単独利用者向けの創業専用知識グラフへ転換するための、製品要件、システム境界、受け入れ条件、実装順序、ADRをまとめた正本である。

- ピボット前のPRD、Postgres中心のアーキテクチャ、Free / Standardの料金設計、Dots内蔵の調査オーケストレーターと矛盾する箇所は、本書を優先する。
- 既存実装は削除前提にせず、Phase 0で再利用、移行、廃止を分類する。
- 事業評価レポートの章名は本書の「事業評価レポート契約」を正本とする。
- ノード、関係、revision、根拠、削除、検索投影の粒度は[`founder-graph-data-model.md`](founder-graph-data-model.md)を正本とする。schema v2契約と実Neo4jの永続化gateが通るまで、通常保存先をin-memoryからNeo4jへ切り替えない。
- 実行DAG、Luna worker運用、並列制御、完了定義は[`dots-implementation-master-plan.md`](dots-implementation-master-plan.md)を正本とする。
- 個別PRは本書から受け入れ条件を引用し、差分500行以内かつレビュー30分以内へ分割する。

## 実装進捗（2026-09-22時点）

初期のデータ境界とMCP縦切りは、外部AI接続なしの合成データ契約として実装済みである。下表は「コード契約と単体検査が完了した」ことを示し、Neo4j実機、ChatGPT接続、Deep Research write-back、実データ運用の完了を意味しない。

| 範囲 | 状態 | 証跡 / 残課題 |
| --- | --- | --- |
| T-FG-02 schema / migration | 実装済み（offline） | `migrate_schema.py --validate-only`。Neo4j実機migrationはSP-FG-05後 |
| T-FG-04 attachment store | 実装済み | content-address、symlink/reparse、quarantine契約テスト |
| T-FG-05〜06 kernel / write境界 | 部分実装（in-memory + Neo4j gateway / write adapter contract） | 競合、冪等、監査、Campaign / Source revision、ReportVersionのRun / Campaign / Claim / Evidence参照、Neo4j bounded node projection、Idea / Claim correction hydrationを検査。Neo4j実機接続とrestoreは残課題 |
| T-FG-07〜09 read / MCP | 部分実装（in-memory + Neo4j read/write contract + stdio transport） | owner、egress、pagination、relation path、MCP error、明示read/write-service注入、停止時503、stdio `initialize` / `tools/list` / `tools/call`を検査。MCP tunnel実機、ChatGPT tool discovery、Neo4j実機unavailableの確認は残課題 |
| T-FG-10 instruction scanner | 実装済み | `AGENTS.md` / `SKILL.md`のallow-root、hash、差分、秘密語除外 |
| T-FG-11〜12 contact / network | 部分実装 | Person / Organization capture、private contact境界、明示link、Mapping/CSV名刺取り込みのlocal normalizerを検査。名寄せ、能力候補、自動関係生成は未実施 |
| T-FG-13〜14 idea capture / enrichment | 部分実装 | capture_idea、全領域read、model catalogの論理Luna境界、shareable入力からの名寄せ・facet・cluster proposal contractを検査。実LLM推論、proposalのwrite-back、実データ評価は未実施 |
| T-FG-15 ResearchBrief | 実装済み（local contract） | shareable Ideas / Assets / Sourcesの一括preflight、canonical URL、relation path、pagination、private除外を検査。ChatGPT実機handoffは未実施 |
| T-FG-16 Campaign lifecycle | 部分実装（local + persistent contract） | 複数試行、期限、scope変更、許諾snapshot、in-memory / Neo4j gatewayのReportVersion参照整合性を検査。完全履歴parityと実機検証が残る |
| T-FG-18〜19 report / impact / T-FG-22 write-back | 部分実装 | 8章shape、用途限定write tool、複数Runの保存契約、固定8章のsafe impact/diff contractを検査。Deep Research実機handoffとfollow-up write-backは未実施 |
| T-FG-01 / T-FG-03 local Neo4j ops | 静的契約 + offline JSON manifest済み | Docker daemon unavailable。permission / Neo4j dump / isolated restore gateは未完了。safe JSON exportのmanifest / verify / dry-runはDocker-freeで検査済み |
| T-FG-24 UI | 実装済み（read-only） | Founder Graph surface、Knowledge右隣のGraph navigation、keyboard / a11y / state tests、Appからのoptional report入力伝播を検査。実DB結果のruntime接続は残課題 |
| T-FG-25〜26 report UI / export | 部分実装 | 8章のsafe projection・差分判定・keyboard/a11y対応の独立ReportDiff componentをFounderGraphSurfaceの任意Reports tabへ接続し、App optional prop伝播、Campaign / Run比較のread-only composition、GraphReadPortからのbounded Campaign comparison adapter、private除外JSON/Markdown export contractを検査。T-FG-26 runtime監査でsafe export / offline manifestと全owner backupを分離。Campaign実データのFastAPI/Neo4j接続、backup / restore / delete / 実ファイルexport UIは未実装 |

## 要望 / ゴール / 成功指標

### 要望

Dotsを、利用者がChatGPTで創業に関する会話をするたびに、アイデア、保有知識、人的ネットワーク、調査資料が蓄積・構造化される個人用グラフデータベースへ転換する。ChatGPTからローカルのDotsへMCPで接続し、アイデアの保存、検索、調査結果の追記、訂正を行えるようにする。Dots自身は独自AIチャット、調査通知、調査ジョブUIを主責務にせず、創業判断へ再利用できるデータ基盤へ集中する。

### ゴール

単独利用者が、ChatGPTで生まれた着想を失わず、過去のアイデア、知識、人脈、根拠、失敗、判断と結び付け、次の事業仮説と低リスクな検証へ再利用できるローカルFounder Graphを構築する。

### 成功指標

- 合成会話20件のアイデア候補を取り込み、原文、抽出結果、関係、生成主体、時刻を100%追跡できる。
- 代表質問10件のうち8件以上で、関連するアイデア、人物、資産、根拠を1件以上返し、回答から出典または保存原文へ到達できる。
- 一つのResearchCampaignに2件以上のResearchRunを保存し、旧Runを変更せずに比較・統合できる。
- 全ReportVersionが指定された8章を持ち、各主張を事実、AI推論、未確認、本人判断へ分類できる。
- Dots停止中はChatGPTから検索・書き込みが失敗し、起動後は同じデータへ再接続できる。
- Neo4jの停止dumpと隔離環境へのloadを実行し、ノード数、関係数、代表検索結果が一致する。
- 名刺由来の連絡先と非公開プロフィールが、明示選択なしに外部Web調査へ送信される件数を0件にする。

## 確定した製品判断

| 項目 | 決定 |
| --- | --- |
| 利用者 | 当面は本人一人だけ。組織、共同編集、一般公開、課金プランを初期対象にしない |
| 稼働形態 | ローカルで起動している間だけ利用可能。停止中のアクセスは提供しない |
| 中心価値 | 創業判断に使えるグラフDB。独自AIチャット、通知基盤、調査実行基盤は中心価値に含めない |
| 主要領域 | Ideas、Assets、Research Sourcesの3領域。人物と組織はAssetsの一部として横断利用する |
| 検知 | ChatGPTがアイデア候補を検知し、Dots内の全体検索を許諾なしで実行する。ChatGPTへ返す値はshareable projectionに限定する |
| フル調査 | ChatGPTが実行前にResearchCampaignの目的、範囲、試行予算を提示し、利用者の許諾後にDeep Researchを開始する |
| 複数試行 | 一つのCampaignに複数Runを持てる。各RunとReportVersionは上書きしない |
| 通知 | 調査の進捗と完了通知はChatGPT側が担当する |
| ローカル書き込み | 可逆かつ履歴付きの保存、名寄せ候補、分類、関係候補は個別承認なしで実行できる |
| 破壊操作 | 物理削除、履歴消去、外部公開、課金、契約、第三者への送信は自動実行しない |
| 初期LLM | Dots側の抽出、名寄せ、分類、facet生成、関係候補、再順位付けはモデルカタログ上のLuna論理キーを初期値とする |
| 将来LLM | 原価またはトークン量が問題になった時点で、同じアダプター契約の背後をローカルLLMへ差し替える |
| グラフDB | Neo4j Communityのローカル運用を第一候補とし、Phase 0の採用スパイクを通過後に確定する |

## プロダクト境界

### ChatGPTの責務

- 会話から創業アイデア、訂正、追加情報を検知する。
- Dotsのread MCPを使って、関連アイデア、人物、知識、調査、過去判断のshareable projectionを取得する。
- フル調査前に目的、対象、情報源、外部へ渡す文脈、試行予算を提示して許諾を得る。
- Deep Researchの実行、再試行、進捗表示、完了通知、追加質問を担う。
- 調査完了後の通常チャットで、Dotsのwrite MCPを使って結果を保存する。

### Dotsの責務

- Ideas、Assets、Research Sources、人物、組織、主張、根拠、判断、試行、レポート版を保存する。
- 全文、グラフ近傍、将来のベクトル検索を統合し、根拠付きの検索結果を返す。
- 名寄せ候補、facet、関係候補を自動生成し、生成主体と確信度を記録する。
- 変更をrevisionまたはeventとして残し、訂正前の状態を失わない。
- データ分類、外部送信用の安全な投影、削除伝播、backup / restoreを担う。
- ローカル検索の全結果とChatGPTへ送る結果を分離し、egress policy、送信先、送信日時、項目区分を監査する。

### Dotsが初期に持たない責務

- ChatGPTと重複する汎用チャットUI。
- Deep Researchそのものの実装。
- 常駐scheduler、メール通知、独自の完了通知。
- 一般ユーザー向け認証、料金プラン、チーム管理。
- 公開MCPマーケットへの配布。

## 利用フロー

1. 利用者がChatGPTで創業に関する発言をする。
2. ChatGPTがアイデア候補を検知し、Dotsへ原文と候補を履歴付きで保存する。
3. Dotsがローカルで全体検索を行い、関連する過去アイデア、人物、知識、調査、判断を選ぶ。
4. DotsはshareableまたはCampaignで明示許可された情報だけをChatGPTへ返す。通常のread MCPとResearchBriefへ、個人連絡先と非公開原文を含めない。
5. ChatGPTが「何を、どの情報源で、何回調べるか」を提示し、フル調査の許諾を得る。
6. ChatGPT Deep ResearchがResearchRunを実行し、ChatGPTが完了を通知する。
7. 同じ目的で別の探索方針を試す場合、新しいResearchRunを同じResearchCampaignへ追加する。
8. ChatGPTがRun同士を比較し、指定8章のReportVersionを生成する。
9. 通常チャットのwrite MCPで、レポート、主張、根拠、関係、判断をDotsへ保存する。
10. 追加質問が外部調査を要する場合は新しいRunを作り、再構成だけなら新しいReportVersionを作る。

## 事業評価レポート契約

章の順序と名称は次で固定する。旧案の「Founder」を含む章名は使わない。

| 章 | 名称 | 必須内容 |
| --- | --- | --- |
| 0 | エグゼクティブサマリー | 事業仮説、現時点の評価、最大の未確認事項、次の判断 |
| 1 | ビジネスモデル | 顧客、課題、提供価値、提供物、販売経路、何を売るか |
| 2 | 顧客とマーケットサイズ | 顧客区分、利用場面、需要根拠、TAM / SAM / SOMの定義・式・前提 |
| 3 | 収益モデル | 価格、販売数量、変動費、固定費、CAC、LTV、損益分岐、資金繰り |
| 4 | 競争優位性 | 直接競合、間接競合、代替手段、他社が実行しない理由、模倣困難性、勝ち筋 |
| 5 | 実現可能性 | 技術、運用、販売、法務、資金、時間、保有知識、人脈、外部依存 |
| 6 | リスク・撤退ライン | 主要リスク、先行指標、確認頻度、継続条件、停止条件、撤退後の処理 |
| 7 | リスクミニマムなロードマップ | 可逆な検証順序、時間・費用上限、各段階の成功条件・失敗条件・次の判断 |

各章は次の区分を別フィールドで持つ。

- 事実: 原典または本人記録に直接支えられる内容。
- AI推論: 事実からモデルが導いた解釈。
- 未確認: 根拠不足、期限切れ、矛盾、未調査の内容。
- 本人判断: 採用、保留、却下、優先順位、許容リスク。
- 引用: SourceRevision、Evidence、取得日時、locator、content hash。

市場規模と財務値は、数値だけを保存しない。式、入力値、単位、期間、通貨、仮説状態、感度を保存する。第6章の撤退ラインと第7章の各段階は同じDecisionCriterionを参照し、相互に矛盾する複製を作らない。

## グラフ情報モデル

本章は製品の概念モデルを定める。Neo4jへの保存単位、stable anchor、immutable revision、RelationAssertion、ContentChunkの物理契約は[`founder-graph-data-model.md`](founder-graph-data-model.md)に従う。

### 3領域と抽象度

Ideas、Assets、Research Sourcesは並列の領域であり、抽象度の階層ではない。各領域を次の共通レイヤーへ投影する。

1. Source Artifact: 会話原文、名刺画像、ファイル、URL、AGENTS.md、SKILL.md。
2. Observation / Claim: 原文から抽出した観察、主張、数値、制約。
3. Canonical Entity: Idea、Person、Organization、Capability、Market、Product、Source。
4. Relation Assertion: エンティティ間の関係と、その根拠、状態、確信度。
5. Facet / Cluster: 業種、モノづくり、コト売り、顧客課題、保有能力の分類軸。
6. Strategic Object: ResearchCampaign、ResearchRun、ReportVersion、Decision、Experiment。

FacetはLLMが提案できるが、コアのnode typeとrelation typeはアプリのallowlistで検証する。LLMが自由な型を永続化することは認めない。

### 最小ノード

| ノード | 役割 |
| --- | --- |
| OwnerProfile | 本人の制約、関心、保有時間、資金上限、判断傾向への参照 |
| Idea | 着想、課題仮説、提供価値、状態、派生元 |
| Asset | 知識、経験、成果物、データ、設備、チャネル、再利用可能な学び |
| Person | 名刺、会話、紹介経路から得た人物。連絡先はprivate属性 |
| Organization | 人物の所属、顧客候補、協業候補、競合候補 |
| Source | 会話、文書、Web、名刺、AGENTS.md、SKILL.mdの論理原本 |
| SourceRevision | 原本の版、取得日時、locator、content hash、利用可否 |
| Claim | 事実候補、推論、未確認事項、本人判断 |
| Evidence | ClaimとSourceRevisionを結ぶ根拠 |
| ResearchCampaign | 許諾された調査目的、範囲、試行予算 |
| ResearchRun | 一回の独立した調査。モデル、情報源、入力、結果、失敗を固定 |
| ReportVersion | 8章レポートの不変版 |
| Decision | 採用、保留、却下、撤回、再検討と理由 |
| Experiment | 低リスクな検証、上限、成功条件、停止条件、結果 |
| InstructionArtifact | AGENTS.md、SKILL.mdとそのpath、scope、hashへの参照 |

### 主要関係

- OwnerProfile - OWNS - Idea / Asset / Source / Campaign。
- OwnerProfile - GOVERNED_BY - InstructionArtifact。
- OwnerProfile - USES_SKILL - InstructionArtifact。
- Idea - REUSES - Asset。
- Idea - ADDRESSES - Claim。
- Idea - DERIVED_FROM - Idea。
- Idea - EVALUATED_BY - ResearchCampaign。
- Person - WORKS_AT - Organization。
- Person - HAS_CAPABILITY - Asset。
- Person - CAN_CONTRIBUTE_TO - Idea。
- Person - INTRODUCED_BY - Person。
- Claim - SUPPORTED_BY / CONTRADICTED_BY - Evidence。
- Evidence - DERIVED_FROM - SourceRevision。
- Source - HAS_REVISION - SourceRevision。
- ResearchCampaign - HAS_RUN - ResearchRun。
- ResearchRun - PRODUCED - ReportVersion。
- ReportVersion - SUPERSEDES - ReportVersion。
- Decision - BASED_ON - Claim / ReportVersion / Experiment。

CAN_CONTRIBUTE_TOとINTRODUCED_BYは自動的に事実扱いしない。状態をinferredまたはproposedとし、根拠、確信度、有効期限を持たせる。

### revisionとprovenance

全ての自動書き込みは、target ID、operation、actor、source ID、model snapshot、prompt / rule version、occurred_at、idempotency keyを記録する。訂正は旧値を消さず、新revisionとSUPERSEDESで表現する。削除は検索・外部投影から除外し、監査に必要なID、hash、削除日時だけを残すsoft deleteを初期値とする。

### AGENTS.mdとSkillのソフト管理

- ファイル本体を正本とし、Dotsはpath、scope、hash、mtime、要約、関連エンティティだけを保持する。
- Dots起動時にhash差分を検知し、InstructionArtifactの新revisionを作る。
- Dotsは変更提案を保存できるが、初期版ではAGENTS.mdとSKILL.mdを自動編集しない。
- ファイルが見つからない場合は参照をunavailableにし、過去revisionを現行ルールとして利用しない。
- 秘密情報、APIキー、環境変数値は取り込まない。

## 技術アーキテクチャ

### 初期構成

- UI: 既存React / Viteを最小の閲覧・訂正・履歴確認UIとして再利用する。
- Application API: FastAPIを唯一のGraphWriteServiceと検索境界にする。
- Graph DB: WSL2のLinux native filesystem上でNeo4j CommunityをDocker Compose運用する。
- Attachments: content hashで識別するローカルファイル領域へ置き、Neo4jにはmetadataとpathだけを保存する。
- MCP: FastAPIと同じdomain serviceを呼ぶread surfaceとwrite surfaceを分ける。
- ChatGPT接続: OpenAI Secure MCP Tunnelのdeveloper-mode接続を第一候補とする。
- Model adapter: 論理能力名からモデルカタログを参照し、製品コードへモデルIDを分散させない。
- Backup: Neo4j停止後のdatabase dumpと、隔離volumeへのdatabase loadを定期検証する。

Neo4jはPhase 0のスパイクで、graph traversal、全文検索、将来のvector index、dump / load、Windows + WSL運用を同じfixtureで確認する。不合格時だけPostgreSQL + pgvectorまたはSurrealDBを再評価する。

- https://neo4j.com/docs/operations-manual/current/docker/
- https://neo4j.com/docs/cypher-manual/current/indexes/semantic-indexes/vector-indexes/
- https://neo4j.com/docs/operations-manual/current/backup-restore/restore-dump/

### MCP surface

read MCPも外部AIへの送信境界である。Neo4jの検索結果をそのまま返さず、egress policyがshareableのfieldだけでSearchResult / FetchOutputを構成する。local_onlyは常に除外し、explicitは有効なCampaign許諾に対象fieldがある場合だけ返す。利用者は初回設定でshareable区分の通常検索を包括許諾し、検索ごとの確認は行わない。OpenAI側が確認を要求する場合、そのplatform確認をDotsから回避しない。

| Surface | Tool | 副作用 | 用途 |
| --- | --- | --- | --- |
| Deep Research read | search | なし | 自然文から安全な検索結果ID、title、canonical URLを返す |
| Deep Research read | fetch | なし | 指定IDの本文、安全なmetadata、引用情報を返す |
| Normal chat write | capture_idea | あり | 会話原文とIdea revisionを冪等保存する |
| Normal chat write | append_claim | あり | 型付きClaim、根拠、生成主体を追記する |
| Normal chat write | link_entities | あり | allowlist済みrelationをproposed / inferredで追加する |
| Normal chat write | save_research_report | あり | Campaign、Run、Evidence、ReportVersionを一括確定する |
| Normal chat write | record_decision | あり | 採否、理由、撤退条件、次の実験を追記する |
| Normal chat write | record_correction | あり | 旧revisionを残して訂正版を作る |

任意Cypher、物理削除、schema変更をMCPへ公開しない。write toolはidempotency key、expected revision、入力schema、relation allowlistを検証する。Deep Researchにはread surfaceだけを接続し、調査結果のwrite-backは通常チャットの別ステップに分ける。

OpenAIのDeep Research互換MCPはread-onlyのsearch / fetchを前提とする。ローカル接続はSecure MCP Tunnelの利用可否を先に検証する。

- https://developers.openai.com/api/docs/mcp
- https://developers.openai.com/api/docs/guides/secure-mcp-tunnels
- https://developers.openai.com/api/docs/guides/deep-research

### Lunaとembedding

- 初期の抽出、名寄せ、group候補、facet候補、関係候補、query expansion、再順位付けはLunaを使う。
- embedding vectorをLunaが生成できるとは仮定しない。Phase 0で対応能力と再現性を検証する。
- Lunaでembeddingを生成できない場合、初期版はgraph traversal + full-text + Luna再順位付けで開始し、別embedding providerを無断追加しない。
- 専用embedding modelまたはローカルembedding modelの採用は、固定評価セットと原価比較を通過後に別ADRで決める。

## 調査許諾と複数試行

ResearchCampaignの許諾記録は、目的、問い、対象Idea、使用可能なDots情報区分、外部情報源、試行予算、有効期限を持つ。

- 試行予算の初期値は1。利用者は開始時に2以上を指定できる。
- 利用者が「もう一度」「別の切り口で」と指示した場合、同じ範囲内なら同じCampaignへRunを追加できる。
- 問い、外部送信するデータ区分、有料情報源、公開範囲が変わる場合は新しい許諾を得る。
- 通信障害へのtransport retryは同じRun内に記録し、調査方針を変える再試行は新しいRunとする。
- 各Runは入力snapshot、モデル、情報源、取得日時、Evidence、失敗、原価指標を固定する。
- 複数Runの統合は新しいReportVersionとして保存し、個別Runの結論を消さない。

## 個人情報と外部送信

- Dots内の全体検索はローカルで実行する。
- 全fieldにlocal_only、shareable、explicitのegress policyを付ける。policy未設定はlocal_onlyとして扱う。
- 通常のread MCPはshareableだけを返す。explicitは有効なCampaign許諾に対象fieldがある場合だけ返す。
- egress policyはLuna呼出にも適用する。実データを初めて処理する前に、利用者が送信先と許可するfield categoryを一度設定し、その範囲内の抽出・名寄せ・分類は項目ごとの確認を行わない。
- local_only fieldはLunaへ送らず、決定的処理、手入力、将来のローカルLLMで扱う。
- Web調査へ渡すResearchBriefはshareableまたはCampaignで許可されたClaimだけで作る。
- Personの氏名、メール、電話、住所、非公開メモはprivateとし、ResearchBriefから既定で除外する。
- 人物を外部調査の対象へ含める場合、Campaign許諾に対象Person IDと送信項目を記録する。
- Webとprivate MCPを一つのモデル文脈で同時に使わず、公開Web調査とprivate graph照合を段階分離する。
- 外部検索結果に含まれる命令文をデータとして扱い、tool指示へ昇格させない。
- MCP request、送信先、外部送信項目のcategory、hash、時刻、Campaign ID、write commandを監査するが、秘密情報と連絡先本文をログへ複製しない。
- OpenAI側の保存期間、workspace policy、接続先はSP-FG-01で記録し、許容できない場合は実データ接続を開始しない。

## ユーザーストーリーと受け入れ条件

### US-FG-01 会話からアイデアを蓄積する

As a 単独利用者, I want ChatGPTで話した着想がDotsへ残ってほしい, so that 会話に埋もれた案を後で再利用できる。

Given: DotsとMCP tunnelが起動し、ChatGPTが創業アイデア候補を検知している

When: ChatGPTがcapture_ideaを同じidempotency keyで複数回呼ぶ

Then: Ideaは一件だけ作成され、原文、抽出値、actor、model snapshot、時刻が追跡できる

### US-FG-02 グラフ全体を事前検索する

As a 単独利用者, I want 新しい着想と過去の資産を自動で照合したい, so that 同じ検討を繰り返さずに済む。

Given: 過去のIdea、Asset、Person、Research Source、Decisionが保存されている

When: ChatGPTが新しいIdeaについてsearchとfetchを実行する

Then: Dotsは全領域をローカル検索し、ChatGPTへはshareable projectionだけを関連理由、関係path、Evidence ID、sensitivity、egress policy付きで返し、local_only fieldを0件とする

### US-FG-03 人的ネットワークを事業へ結び付ける

As a 単独利用者, I want 人物の知識と紹介経路をアイデアへ結び付けたい, so that 誰と何を検証できるか考えられる。

Given: 名刺または会話からPerson、Organization、Capability候補が作られている

When: DotsがCAN_CONTRIBUTE_TOまたはINTRODUCED_BYを生成する

Then: 関係は根拠、確信度、有効期限、inferredまたはproposed状態を持ち、事実として断定されない

### US-FG-04 フル調査を許諾して複数回試す

As a 単独利用者, I want 一度決めた調査目的を複数の切り口で試したい, so that 一回の結果へ依存せず比較できる。

Given: 目的、範囲、外部送信項目、試行予算2以上を持つCampaignを許諾している

When: ChatGPTが二回以上のDeep Researchを実行する

Then: Runごとの入力、Evidence、結果、失敗が不変で保存され、比較結果が新しいReportVersionになる

### US-FG-05 8章の事業評価を読む

As a 単独利用者, I want 同じ章立てで事業性を評価したい, so that アイデア間と試行間を比較できる。

Given: 一件以上のResearchRunとEvidenceがある

When: ChatGPTが事業評価レポートを生成してDotsへ保存する

Then: ReportVersionは0から7の指定章を持ち、事実、AI推論、未確認、本人判断、引用を区別する

### US-FG-06 追加質問でレポートを改訂する

As a 単独利用者, I want レポートへ疑問を投げて追調査したい, so that 新しい競合や反証を反映できる。

Given: 現行ReportVersionへ「この会社も同種ではないか」と質問している

When: 外部調査または再構成が完了する

Then: 影響章、追加・撤回Claim、追加Evidence、変更理由を持つ新ReportVersionが作られ、旧版は残る

### US-FG-07 AGENTS.mdとSkillを本人情報へ結び付ける

As a 単独利用者, I want 自分の指示と手順を資産として参照したい, so that AIの提案が自分の作業方式と矛盾しにくくなる。

Given: 許可されたAGENTS.mdまたはSKILL.mdが存在する

When: Dots起動時にファイルhashが変わっている

Then: InstructionArtifactの新revisionが作られ、旧revisionを現行ルールとして返さず、ファイル本体は自動編集されない

### US-FG-08 停止と復旧を管理する

As a 単独利用者, I want Dots停止中はデータへ接続できない状態にしたい, so that 常時公開サービスを運用せずに済む。

Given: Neo4j、FastAPI、MCP tunnelが停止している

When: ChatGPTがsearchまたはwrite toolを呼ぶ

Then: 明示的なunavailableを返し、公開fallback DBへ切り替わらず、再起動後に同じrevisionへ接続できる

### US-FG-09 履歴と削除を追跡する

As a 単独利用者, I want 訂正と削除の影響を確認したい, so that 古い情報を現行の根拠として使わずに済む。

Given: Claimの訂正またはSourceの削除を実行している

When: 検索、レポート再生成、exportを行う

Then: 現行検索から旧内容が除外され、過去レポートには参照不能、hash、変更日時が表示される

## 質問リスト

| ID | 質問 | 決定者 | 判断期限 |
| --- | --- | --- | --- |
| Q-FG-01 | 対象ChatGPT workspaceでSecure MCP Tunnelとdeveloper modeを利用できるか | 技術責任者 | SP-FG-01完了時 |
| Q-FG-02 | Deep Research完了後の通常チャットへwrite-backを連続実行できるか、利用者の一言を要するか | 技術責任者 | SP-FG-02完了時 |
| Q-FG-03 | 既存PostgresデータをNeo4jへ移すか、JSON export後に旧データをread-only保持するか | 利用者 | SP-FG-03のinventory提示後 |
| Q-FG-04 | Lunaでembedding vectorを生成できない場合、vector検索を延期するか、専用モデルを追加するか | 利用者 | SP-FG-04の評価提示後 |
| Q-FG-05 | 名刺画像の初期入力を手入力、CSV import、ローカルOCRのどこまで含めるか | 利用者 | SP-FG-06の比較提示後 |

## スコープ外

- 複数利用者、組織、共同編集、招待、権限ロール。
- Free / Standard / Pro、課金、利用量販売、一般公開。
- Dots独自のDeep Research、scheduler、メール、push通知。
- 常時稼働のcloud DB、公開MCP endpoint、モバイル常時同期。
- 名刺の相手への自動連絡、営業メール、自動投稿。
- 任意Cypher、schema変更、物理削除を行うMCP tool。
- 初期版でのローカルLLMと専用embedding model。
- 法務、税務、融資、投資、特許性の保証または代理判断。

## 既存成果物の再利用方針

| 既存成果物 | 再利用する契約 | ピボット後の位置づけ |
| --- | --- | --- |
| [アイデアストックと仮説カード](../spec/idea-candidates-plan.md) | 会話保存、重複検知、訂正 | Idea revisionとcapture_ideaへ移植する |
| [横断調査・個人ナレッジ・意思決定記憶](../spec/research-memory-plan.md) | Evidence、出典、削除伝播、過去判断 | Neo4jのClaim / Evidence / Decisionへ移植する |
| [市場・3種競合](issue-64-market-slice.md) | 直接、間接、代替、潜在参入、本人判断 | 第2章と第4章の入力contractとして再利用する |
| [unit economics](issue-65-unit-economics-contract.md) | Decimal、CAC、LTV、損益分岐、3シナリオ | 第3章の決定的計算moduleとして再利用する |
| [低リスク実行契約](issue-66-low-risk-execution-contract.md) | 時間・資金上限、可逆性、撤退条件、roadmap | 第5章から第7章の共通DecisionCriterionへ移植する |
| [フォーマル事業計画書export](issue-68-formal-business-plan-export.md) | adapter、未確定表示、privacy、attribution | 8章ReportVersionを入力とするexportへ更新する |

既存moduleを再利用する場合も、PostgresのID、owner前提、5観点payloadをそのまま新しい正本にしない。Phase 0のinventoryでdomain logic、storage、UI、test fixtureを別々に分類する。

## 実装フェーズ

### Phase 0: 不確実性を潰す

コード移行前に接続、DB、model capability、既存データを合成データで検証する。本Phaseの不合格項目を回避策なしで本実装へ進めない。

| ID | 成果物 | 依存 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- | --- |
| SP-FG-01 | Neo4j + FastAPI + read MCP + Secure MCP Tunnelの縦切り | なし | 検査: Dots起動中だけChatGPTからsearch / fetchが成功し、停止中はunavailableになる。workspace、接続先、保存期間、credential境界を記録する | 未知・先行スパイク |
| SP-FG-02 | Deep Researchから通常チャットwrite-backへのhandoff試験 | SP-FG-01 | 検査: 合成レポートを一意のRun / ReportVersionとして保存し、再送しても重複しない | 未知・先行スパイク |
| SP-FG-03 | 既存Postgres、local fake、UI、exportの移行inventory | なし | 検査: 各機能を再利用、変換、read-only保持、廃止へ分類し、データ件数とrollbackを記録する | 未知・先行スパイク |
| SP-FG-04 | Lunaの抽出、名寄せ、分類、再順位付け、embedding capability評価 | なし | 検査: 固定20件で必須field抽出F1 0.90以上、同一人物候補top-3再現率0.90以上、誤統合0件、不正core type 0件、関連結果top-5命中16件以上、p95 30秒以下を満たす。未達機能は自動実行を採用せず、規則処理、手入力、延期のいずれかをQ-FG-04へ提示する | 未知・先行スパイク |
| SP-FG-05 | Neo4j採用判定とrestore drill | なし | 検査: 代表10問中8問以上、provenance 100%、停止dump / 隔離load、再起動後の一致を確認する | 未知・先行スパイク |
| SP-FG-06 | 手入力、CSV import、ローカルOCRの名刺入力比較 | なし | 検査: 合成名刺10件でfield精度、重複候補、処理時間、外部送信0件を比較し、Q-FG-05の初期範囲を決める | 未知・先行スパイク |

### Phase 1: ローカルGraph基盤

| ID | 成果物 | 依存 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- | --- |
| T-FG-01 | WSL2 / Docker Compose、Neo4j volume、health、start / stop runbook | SP-FG-05 | 検査: clean環境の起動、停止、再起動、認証、volume永続化を自動確認する | 類推可能 |
| T-FG-02 | constraint、index、migration runner、schema version | T-FG-01 | 検査: migration再実行が冪等で、重複IDと不正relationを拒否する | 類推可能 |
| T-FG-03 | dump / load、世代管理、restore検証script | T-FG-01 | 検査: neo4jとsystemを復元し、node / relation件数と代表3問が一致する | 類推可能 |
| T-FG-04 | content-addressed attachment store | T-FG-02 | 検査: 同一hashの重複保存、削除、missing file、path traversalを契約テストする | 類推可能 |

### Phase 2: Graph kernelとread / write境界

| ID | 成果物 | 依存 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- | --- |
| T-FG-05 | core nodes、relations、state、revision、provenance schema | T-FG-02 | 検査: Idea訂正、Person関係候補、Source削除、SUPERSEDESをgraph contract testで確認する | 類推可能 |
| T-FG-06 | GraphWriteServiceとcommand schema | T-FG-05 | 検査: idempotency、expected revision、allowlist、rollback、監査eventが全commandで通る | 類推可能 |
| T-FG-07 | hybrid read serviceのgraph + full-text版 | T-FG-05 | 検査: 代表10問、relation path、pagination、timeout、sensitivity filterを確認する | 類推可能 |
| T-FG-08 | MCP read surface search / fetch | T-FG-07 | 検査: OpenAI互換schema、canonical URL、read-only、入力上限、prompt injection、egress policyを確認し、local_only fieldの返却を0件にする | SP-FG-01後に類推可能 |
| T-FG-09 | MCP write surface | T-FG-06 | 検査: 8個の用途限定toolが任意Cypherと物理削除を拒否し、再送で重複しない | SP-FG-02後に類推可能 |

### Phase 3: Assets、人物、指示ファイル

| ID | 成果物 | 依存 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- | --- |
| T-FG-10 | AGENTS.md / SKILL.md scannerとInstructionArtifact | T-FG-05 | 検査: path許可、hash差分、missing、秘密語除外、非自動編集を確認する | 類推可能 |
| T-FG-11 | Person / Organization / business-card intake第一版 | SP-FG-06, T-FG-06 | 検査: 合成人物10件の重複候補、所属、連絡先private化、削除伝播を確認する | SP-FG-06後に類推可能 |
| T-FG-12 | Asset / Capability / network relation candidate | T-FG-11, SP-FG-04 | 検査: CAN_CONTRIBUTE_TOが根拠、確信度、期限、inferred状態なしでは保存されない | 類推可能 |

### Phase 4: アイデア検知と再利用検索

| ID | 成果物 | 依存 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- | --- |
| T-FG-13 | capture_ideaとIdea revision | T-FG-06, SP-FG-04 | 検査: 合成会話20件、重複送信、訂正、派生Idea、失敗再送を確認する | 類推可能 |
| T-FG-14 | name resolution、facet、cluster proposal | T-FG-07, SP-FG-04 | 検査: 候補はmodel snapshotと根拠を持ち、core typeを増やさず、local_only fieldをLuna requestへ含めない | 類推可能 |
| T-FG-15 | 全領域preflight searchとResearchBrief | T-FG-08, T-FG-12, T-FG-13 | 検査: Ideas / Assets / Sourcesを検索し、private fieldを外したbriefを生成する | 類推可能 |

### Phase 5: 調査と8章レポート

| ID | 成果物 | 依存 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- | --- |
| T-FG-16 | ResearchCampaign許諾snapshotと試行予算 | T-FG-05 | 検査: default 1、2以上、期限切れ、scope変更、private項目追加を状態遷移で確認する | 類推可能 |
| T-FG-17 | immutable ResearchRun、Evidence、retry / comparison | T-FG-16 | 検査: transport retryと新Runを分離し、partial、failed、completedを再現する | 類推可能 |
| T-FG-18 | 8章ReportVersion schemaとsave_research_report | T-FG-09, T-FG-17 | 検査: 指定章名、区分、引用、財務式、撤退ライン、roadmap、SUPERSEDESを確認する | 類推可能 |
| T-FG-19 | follow-up impact analysisと部分改訂 | T-FG-18 | 検査: 影響章だけが新内容を持ち、据え置き章は親版参照、旧版は不変である | 類推可能 |

### Phase 6: ChatGPT統合

| ID | 成果物 | 依存 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- | --- |
| T-FG-20 | private developer-mode MCP接続runbook | SP-FG-01, T-FG-08, T-FG-09 | 部分実装。stdio adapter、network-free validatorでcredential非表示、doctor、起動、停止、再接続、失効手順を確認し、実機gateでtunnel-client / ChatGPT接続を確認する | 類推可能 |
| T-FG-21 | idea detectionから許諾前preflightまでのChatGPT手順 | T-FG-13, T-FG-15 | 部分実装。ローカル保存・全体検索・shareable preflightはfixtureで検査済み。代表会話5件のChatGPT検知、許諾表示、外部調査0件は実機証跡P6-E1が必要 | SP-FG-01 / 04後に類推可能 |
| T-FG-22 | Deep Research、複数Run、通知、write-back手順 | T-FG-18, T-FG-20 | 部分実装。複数Run、ReportVersion参照、冪等保存はfixtureで検査済み。1回、2回、追加質問の通知・handoff・旧版不変は実機証跡P6-E2〜E4が必要 | SP-FG-02後に類推可能 |
| T-FG-23 | public / private段階分離とexfiltrationテスト | T-FG-15, T-FG-22 | 部分実装。shareable allowlist、ResearchBrief、prompt injection、owner境界はfixtureで検査済み。悪性Web fixtureの実query・payload照合は実機証跡P6-E5が必要 | SP-FG-01後に類推可能 |

### Phase 7: 最小UIと運用

| ID | 成果物 | 依存 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- | --- |
| T-FG-24 | Ideas / Assets / Sources / Peopleの一覧と詳細 | T-FG-12, T-FG-15 | 検査: PC、mobile、keyboard、a11y、empty、unavailableのStoryとtestが通る | 類推可能 |
| T-FG-25 | Campaign / Run比較、8章ReportVersion、差分、訂正UI | T-FG-19 | 検査: 2 Run比較、版差分、引用、撤回Claim、本人判断をE2Eで確認する | 類推可能 |
| T-FG-26 | backup、restore、delete、Markdown / JSON export UI | T-FG-03, T-FG-25 | 検査: 復元演習、削除伝播、全ownerデータexport、外部送信0件を確認する | 類推可能 |

### Phase 8: 移行とhardening

| ID | 成果物 | 依存 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- | --- |
| T-FG-27 | 既存Postgres / local fakeの変換またはread-only archive | Q-FG-03, Phase 1-7 | 検査: inventory件数、変換件数、失敗一覧、rollback、旧版参照を照合する | SP-FG-03とQ-FG-03後に類推可能 |
| T-FG-28 | 旧料金、認証、内蔵調査UIの撤去計画と実行 | T-FG-27 | 検査: dead route、dead config、旧copy、不要secret参照が0件である | 類推可能 |
| T-FG-29 | threat model、負荷、障害注入、運用文書 | T-FG-23, T-FG-26 | 検査: prompt injection、DB停止、disk不足、tunnel切断、restoreを演習する | 類推可能 |
| T-FG-30 | local LLM差し替え評価 | 利用量または原価の閾値超過 | 検査: Lunaと同一fixtureで品質、latency、memory、rollbackを比較する | 未知・将来スパイク |

## フェーズゲート

- Gate A: SP-FG-01、02、05が通るまで、Neo4j移行とChatGPT本接続を開始しない。
- Gate B: T-FG-05から09のrevision、provenance、read / write分離が通るまで、実データを入れない。
- Gate C: T-FG-15、16、23のprivate data分離が通るまで、名刺と非公開プロフィールをDeep Researchへ接続しない。
- Gate D: backup / restore、delete、exportを実データfixtureで通すまで、旧Postgresを廃止しない。
- Gate E: local LLMは原価またはtoken量の閾値が実測されるまで実装しない。

## ADR

ADR-FG-01からADR-FG-10の決定日は2026-09-20、決定者は利用者兼製品責任者とする。スパイク結果で変更する場合は、旧行を消さずに変更日、決定者、根拠を変更履歴へ追加する。

| 判断 | 選択と理由 | 却下案と理由 | 結果 / 見直し条件 |
| --- | --- | --- | --- |
| ADR-FG-01 製品形態 | 単独利用者向けlocal-first Founder Graph。本人の利用密度を優先できる | 初期からSaaS / multi-tenantは認証、課金、共有へ投資が分散するため却下 | 共同利用の反復需要が観測された場合だけ再評価 |
| ADR-FG-02 AI責務 | ChatGPTが対話、Deep Research、通知を持ち、DotsはDBへ集中する | Dots内に汎用AIを重複実装する案は価値の核を薄めるため却下 | ChatGPTから実行不能な必須機能が判明した場合に限定再評価 |
| ADR-FG-03 DB | Neo4j Communityを第一候補とする。関係探索、Cypher、全文、vector拡張、GraphRAG資産が要件に合う | Postgres + pgvector単独は既存資産を再利用できるが、graph relationと履歴をアプリ側で組む比率が高い。SurrealDBは採用資産が少ない | SP-FG-05不合格時に代替を同一fixtureで比較 |
| ADR-FG-04 MCP境界 | Deep Research readと通常chat writeを分離し、用途限定toolだけ公開する | 任意Cypherは破壊操作、schema逸脱、prompt injectionの影響が大きいため却下 | OpenAI側のtool契約変更時に再評価 |
| ADR-FG-05 データモデル | 3領域と共通抽象レイヤーを分ける | 領域ごとに独立schemaを作る案はClaim、Evidence、revisionを重複させるため却下 | core typeはmigrationでのみ追加する |
| ADR-FG-06 変更履歴 | append / revision / SUPERSEDESを既定にする | LLMの直接上書きは訂正理由と過去判断を失うため却下 | 物理削除は明示操作とbackup方針を別途要求する |
| ADR-FG-07 LLM | 初期はLuna論理キーへ集約し、provider adapterを維持する | タスクごとにモデルIDを直書きする案は移行と原価計測を壊すため却下 | 固定評価で品質、token、latencyを再判定する |
| ADR-FG-08 embedding | Luna非対応ならvectorを延期し、graph + full-text + rerankで開始する | 未承認の専用embedding provider追加は「初期はLuna」の決定に反するため却下 | Q-FG-04で利用者が追加を選んだ場合に変更する |
| ADR-FG-09 調査版管理 | Campaignの下に複数の不変RunとReportVersionを置く | 同じrunへ結果を追記する案は試行比較と再現を壊すため却下 | transport retryだけ同一Run内に保持する |
| ADR-FG-10 private data | Dots内全体検索と外部送信用projectionを分ける | private graphとWebを同時に自由検索させる案はexfiltration riskが高いため却下 | threat modelと悪性fixtureを継続更新する |

## リスクと停止条件

| リスク | 検知 | 対応 | 停止条件 |
| --- | --- | --- | --- |
| Secure MCP Tunnelを利用できない | SP-FG-01で接続不能 | 公開endpointを作らず、Responses APIまたは手動handoffを比較 | private接続手段が確立するまでChatGPT統合を停止 |
| Deep Research後のwrite-backが連続しない | SP-FG-02でhandoff不能 | 完了後の通常チャットcommandまたは一回の利用者操作へ分離 | 調査中のwrite権限追加は行わない |
| private data流出 | auditで非許可fieldを検出 | safe projection停止、該当Campaign失効、credential rotation | 原因とfixture修正が完了するまで外部調査を停止 |
| LLMによるgraph汚染 | 重複率、根拠なしrelation率、訂正率が閾値超過 | relation語彙縮小、confidence閾値、候補の隔離 | 出典なしwriteが1件でも通れば自動enrichmentを停止 |
| Neo4j破損または復元失敗 | restore drill不一致 | 新規write停止、直近検証済みdumpへrollback | restoreが再現するまで旧DB廃止を停止 |
| 人物情報の過収集 | private field増加と未参照率を監査 | 保存項目削減、保持期限、削除UI | 利用目的を説明できないfieldの取り込みを停止 |
| Luna品質または原価悪化 | 固定fixture、token、latencyの回帰 | prompt縮小、batch、cache、local LLM評価 | 根拠付き精度または予算上限を2回連続で下回れば自動処理を停止 |
| 旧実装との二重正本 | 同一IdeaのID / revision不一致 | write先を一つに固定し、旧系をread-only化 | dual-writeが必要なら移行を停止してADRを更新 |

## 検査計画

文書変更では次を実行する。

- 章名と順序の検索。
- 本計画の全ユーザーストーリーにGiven / When / Thenがあることの照合。
- 禁止曖昧語の検索。
- 相対リンクの存在確認。
- git diff --check。

実装PRでは変更範囲に応じて次を実行する。

- npm run test
- npm run build
- npm run build-storybook
- uv run pytest
- git diff --check

DB migration、MCP tool、privacy境界、backup / restoreは、unit testだけで完了扱いにせず、合成データによるintegration testとrestore drillを要求する。

## ロールバック方針

- Phase 0から7は既存Postgresを削除せず、Neo4jへの新規writeをfeature flagで停止できる状態を保つ。
- migration前に既存データのJSON export、件数、hashを保存する。
- Neo4j schema migrationはforward migrationと、直前dumpへ戻すrestore手順を同じPRへ含める。
- MCP tool変更は旧schemaを一定期間受け付け、ChatGPT側設定を先に戻せる順序で展開する。
- ReportVersionとResearchRunはrollback時も削除せず、失効状態と理由を追記する。

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-09-20 | 初版。単独利用、Founder Graph、Neo4j候補、ChatGPT Deep Research責務、複数Run、8章レポートを定義 | 利用者とのピボット方針が確定したため | SP-FG-01からT-FG-30 |
| 2026-09-22 | Source / SourceRevision、Campaign複数Run、Luna論理カタログ、Neo4j parameterized gateway/read adapter、Founder Graph read-only UIを実装状況へ反映 | 利用可能なコード契約と未検証の実機境界を分離するため | T-FG-05〜09、T-FG-13〜18、T-FG-24 |
| 2026-09-22 | FastAPIへread serviceの明示注入境界を追加し、停止時をMCP `unavailable` / HTTP 503へ統一 | in-memory既定を保ちつつNeo4j実機採用と停止中の再試行契約を分離するため | T-FG-07〜09、Q-NGR-01 |
| 2026-09-22 | Secure MCP Tunnelのnetwork-free runbook / validatorを追加し、現行FastAPI adapterが標準MCP transportではないことを明記 | 実credential・実tunnel IDなしでprivate接続境界と実機gateの残差を検査可能にするため | T-FG-20、SP-TUNNEL-01 |
| 2026-09-22 | dependency-free stdio JSON-RPC transportを追加し、Secure Tunnelの`--mcp-command`から既存surfaceへ委譲 | ChatGPT / Tunnel接続前に標準的なinitialize・tools discovery・tool call境界を固定するため | T-FG-07〜09、T-FG-20 |
| 2026-09-22 | Person / Organization captureを8番目までの用途限定write surfaceへ追加し、private contactをlocal_onlyへ固定 | 人的ネットワークの最小取り込みを関係自動生成なしで可能にするため | T-FG-11〜12 |
| 2026-09-22 | shareable専用ResearchBrief builderを追加し、preflightのIdeas / Assets / Sources集約とprivate除外を検査 | フル調査前にDots全体検索の事前情報を一つの不変projectionへまとめるため | T-FG-15 |
| 2026-09-22 | Neo4j write gatewayのSource親・revision chain・current pointer検証を同一transactionへ追加 | direct gateway経由でもowner境界とappend-only履歴を迂回できないようにするため | T-FG-05〜06 |
| 2026-09-22 | Neo4j persisted write adapter、bounded hydration、read/write同一gatewayの明示composition helperを追加 | in-memory writeとNeo4j readの混在を防ぎ、再起動後の永続経路を検査可能にするため | T-FG-05〜09、SP-FG-01 |
| 2026-09-22 | Phase 6接続前契約監査とP6-E1〜E5 redacted evidence contractを追加 | ローカルfixtureで確認できる境界とChatGPT実機でしか証明できない検知・許諾・通知・外部queryを分離するため | T-FG-21〜23、SP-P6-01〜03 |
| 2026-09-22 | 8章ReportVersionのsafe projectionと差分表示を独立UI componentとして追加 | 後続のApp composition前に、章名・差分・撤回Claim・provenance表示の契約を固定するため | T-FG-25 |
| 2026-09-22 | Luna logical snapshotを持つlocal-only enrichment proposal contractを追加 | core schemaを増やさず、名寄せ・facet・cluster候補を安全なshareable projectionからfixture検証できるようにするため | T-FG-14 |
| 2026-09-22 | Mapping / CSVの名刺取り込みnormalizerを追加し、contactとprivate_notesをlocal_onlyへ固定 | 既存8-toolへ渡せる人的資産の最小入力を、OCR・自動関係生成なしで安全に用意するため | T-FG-11 |
| 2026-09-22 | 固定8章のReportVersion impact/diff contractを追加し、follow-upの影響章とprovenance metadataを純粋に算出 | 追加質問・追加Evidenceで旧版を変更せず部分改訂へ進める境界を固定するため | T-FG-19 |
| 2026-09-22 | owner-scoped safe projectionから決定的JSON / Markdown export contractを追加 | 外部送信やUI実装前に、private/local-only/provenance境界を検査可能にするため | T-FG-26 |
| 2026-09-22 | Campaign / Run比較のread-only compositionとfocused testsを追加 | 既存の8章ReportDiffを複数試行へ再利用するUI境界を固定するため | T-FG-25 |
| 2026-09-22 | GraphReadPortからCampaign / Run / ReportVersionをboundedに合成するsafe read adapterを追加 | UIへ実データを接続する前にowner・node type・private field境界を固定するため | T-FG-25 |
| 2026-09-22 | Neo4j persistent writeへReportVersionのRun / Campaign / Claim / Evidence参照validatorとfake-driver契約テストを追加 | in-memoryだけでなく永続mutation前にもauthorizationとsection evidence対応を検査するため | T-FG-05〜06、T-FG-16 |
