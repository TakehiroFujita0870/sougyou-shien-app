# Founder Graph データモデル正本

本書は現行の保存単位、意味関係、改訂、根拠、削除、検索投影の契約を定める。製品体験は[製品方針](founder-graph-pivot.md)、現在の実装・検証状態は[現況](../operations/dots-current-status.json)と現行コードを参照する。Markdownレポートの一本化と、下書き・過去調査からの意味関係作成は[全体計画](dots-implementation-master-plan.md)で決定済みの変更目標であり、実装時に本書のReportVersion・IdeaBrief・RelationAssertion契約を更新する。旧schemaへの移行経緯や完了した試験はGit・PR履歴に残し、過去の未完了欄を現在の残件とみなさない。

安定した対象IDと不変の改訂を分ける。事業上の関係は根拠・状態・確信度を持つRelationAssertionを正本とし、保存や版管理の構造edgeとは区別する。MCPへ返すのは共有可能な投影だけで、ローカル原文や連絡先をそのまま返さない。

新規の題名・要約・主張・分類語・事業評価は日本語を基本とする。資料の原題、固有名詞、URL、引用は原文を保持する。Neo4jの型名・関係識別子は安定した保存契約として維持し、利用者向け画面では日本語の名称へ投影する。既存本文の一括翻訳は行わない。
## モデル化の判定規則

情報を新しいノードにする条件は次のいずれかである。

1. 独立したIDとライフサイクルを持つ。
2. 二つ以上の対象から参照される。
3. 根拠、送信区分、訂正履歴を単独で持つ。
4. Graph traversalの始点または終点になる。
5. 引用、判断、実験、レポートからIDで参照される。

上記を満たさず、一つのrevisionに従属するscalar、短い文字列、順序付き小配列はpropertyにする。binary、長文原本、秘密情報はNeo4j propertyへ複製せず、local content storeへ置いてhashとlocatorだけをGraphへ保存する。

## schema v2のノード単位

### 安定anchor

安定anchorは同一物を表し、訂正でIDを変更しない。表示内容はCURRENT_REVISION先から取得する。

| Label | 一ノードの単位 | 安定ID | 主な索引field |
| --- | --- | --- | --- |
| OwnerProfile | 本人一人 | `owner_<uuid>` | owner_id |
| Idea | 一つの事業着想または派生案 | `idea_<uuid>` | owner_id, status, current_revision_id |
| Asset | 本人の知識・経験等、または創業をためらわせる弱み・迷い一件 | `asset_<uuid>` | owner_id, asset_kind, status |
| Person | 同一人物候補の確認後に確定した一人 | `person_<uuid>` | owner_id, status, dedupe fingerprint |
| Organization | 一つの法人、団体、個人事業、非公式チーム | `org_<uuid>` | owner_id, status, normalized_name_hash |
| Source | 一つの原本系列 | `source_<uuid>` | owner_id, source_kind, locator_hash, status |
| ResearchCampaign | 一回許諾した目的、範囲、試行予算 | `campaign_<uuid>` | owner_id, status, authorization_revision |
| Decision | 一つの判断論点 | `decision_<uuid>` | owner_id, status, decided_at |
| Experiment | 一つの可逆な検証 | `experiment_<uuid>` | owner_id, status, deadline |
| InstructionArtifact | 一つのAGENTS.mdまたはSKILL.mdのpath | `instruction_<uuid>` | owner_id, path_hash, status |
| Facet | 再利用する分類語彙 | `facet_<uuid>` | owner_id, namespace, normalized_value |

`Capability`は初期schemaで独立Labelにしない。`Asset.asset_kind=capability`として保存し、Person、OwnerProfile、IdeaからRelationAssertionで参照する。MarketとProductも初期schemaではClaimまたはFacetとして保存し、独立ライフサイクルが必要になった時点でmigration ADRを作る。

弱み・迷いは`Asset.asset_kind=barrier`で保存する。既存Assetのkindは強み・経験として扱い、過去データの一括変更はしない。barrierを再利用可能な強みとして`REUSES`関係へ結び付けない。ChatGPTへ返すのは明示的に共有可能とした短い記述だけで、機微な詳細の既定値は非共有とする。

### 不変ノード

不変ノードは作成後に本文を更新しない。訂正は新しいノードとSUPERSEDESで表す。

| Label | 一ノードの単位 | 必須field |
| --- | --- | --- |
| EntityRevision | anchor一件の一版 | id, entity_id, entity_type, revision, payload_schema, public_payload_json, local_content_ref, content_hash, created_at, provenance_id |
| SourceRevision | Source一件の一取得版または一編集版 | id, source_id, revision, locator, content_hash, captured_at, egress_policy |
| ContentChunk | SourceRevision内の引用可能な一範囲 | id, source_revision_id, ordinal, char_start, char_end, text_hash, textまたはcontent locator |
| Claim | 一つの主語・述語・目的語または一つの数値仮説 | id, claim_type, text, confidence, status, created_at |
| Evidence | 一つのClaimと一つの保存済みContentChunkの対応 | id, polarity, source_revision_id, content_chunk_id, char_start, char_end, content_hash, confidence, egress_policy |
| RelationAssertion | sourceとtarget間の意味関係一件 | id, owner_id, assertion_family_id, revision, predicate, basis, status, confidence, valid_from, expires_at, supersedes_id, provenance_id, egress_policy |
| CampaignAuthorizationSnapshot | Campaignで本人が許諾した目的、範囲、送信field、試行予算の一版 | id, campaign_id, revision, purpose, scope_hash, field_categories, run_budget, expires_at, authorized_at |
| ResearchRun | 一回の独立調査 | id, campaign_id, input_snapshot_hash, model_snapshot, status, started_at, completed_at |
| ReportVersion | 一回確定した8章レポート | id, campaign_id, parent_report_id, status, created_at |
| ReportSection | ReportVersion内の一章 | id, report_version_id, section_id 0-7, content_hash |
| AuditEvent | 一つのwrite command結果 | id, operation, actor, target_id, idempotency_key, payload_fingerprint, occurred_at |
| Attachment | local content store内の一blob | id, sha256, media_type, size_bytes, relative_locator, encryption_state |

ContentChunkは原文の構造境界を優先し、目標1,200〜2,400 Unicode文字、上限4,000文字とする。表、見出し、段落を途中で切らない。各chunkはchar offsetとhashを持ち、原本を変更した場合は既存chunkを更新せず、新SourceRevision配下へ再生成する。

## Sourceの粒度

Source一件は「同じlocatorで更新される原本系列」とする。

| 入力 | Source単位 | SourceRevision単位 |
| --- | --- | --- |
| ChatGPT会話 | 保存対象となった一発言または選択範囲 | 原則一版。訂正保存時だけ次版 |
| 名刺 | 一枚の名刺画像または一件のCSV row | OCR、手修正ごとに新しい版 |
| ファイル | 一つの論理path | content hashが変わるごとに新しい版 |
| Web | 一つのcanonical URL | 取得content hashが変わるごとに新しい版 |
| AGENTS.md / SKILL.md | 一つの絶対pathとscope | hashが変わるごとに新しい版 |
| 手入力メモ | 一つのメモ | 保存確定ごとに新しい版 |

会話thread全体を一つの巨大SourceRevisionにしない。conversation IDとmessage IDはmetadataとして保持し、保存対象発言だけを独立Sourceへする。

## revision契約

1. anchor IDは変えない。
2. EntityRevisionは`(owner_id, entity_id, revision)`で一意にする。
3. revisionは1から開始し、欠番を作らない。
4. 新revision作成とCURRENT_REVISION差し替えを一transactionで行う。
5. 過去revisionを更新しない。
6. Correctionは旧revision ID、新revision ID、理由、actor、時刻をAuditEventへ記録する。
7. Claim、RelationAssertion、ResearchRun、ReportVersionは不変とし、訂正時はSUPERSEDES chainを作る。
8. current pointerが二件、欠落、別ownerを指す場合はwriteをrollbackする。

## IdeaBriefとMarkdown読取projection

`IdeaBriefVersion.report_markdown`がある版では、それを人が読むレポート本文の正本とする。新しい調査済み保存は本文をMarkdownで検証し、`sections`には章ごとのfacts、inferences、unconfirmed、owner_decisions、Claim ID、Evidence IDを保持する。章本文を`sections[].content`へ重複入力する必要はなく、互換のため受け取った場合も新しい保存版には残さない。

read adapterはMarkdown本文を変更せず、T-3a parserが返す文字offsetから必要な章本文を読み取り時に導出する。derived bodyは既存APIの`sections[].content`形状を維持するための応答値であり、別の保存正本ではない。Markdownがない既存Briefは、旧`sections[].content`をそのまま返す。

正規見出しが重複・順不同でprojectionがambiguousの場合、Markdown由来の章本文を空にし、URLの章対応とその版を根拠とするrelation pathを返さない。公開URLは`citation_metadata`で検証したURL-onlyリンクとしてEvidence citationsと別に投影する。Evidence citationsは既存`evidence_ids`から所有者、状態、shareability、現行Source系譜を検証したものだけを返す。見出しやURLが存在するだけではClaim・Evidenceを生成しない。

## RelationAssertion契約

業務上の意味関係はNeo4j relationship propertyだけを正本にせず、RelationAssertionノードを正本とする。

RelationAssertionは次の構造edgeを持つ。

- `ASSERTS_FROM` → source anchorまたはClaim。
- `ASSERTS_TO` → target anchor、Claim、Facet。
- `EVIDENCED_BY` → Evidenceを0件以上。inferred、confirmedは1件以上を必須にする。
- `SUPERSEDES` → 直前のRelationAssertion。状態変更時に使用する。

`basis=external_evidence`はsource-grounded Evidenceを必須とする。`basis=brief_hypothesis`はIdeaBrief由来の未確定な`proposed`関係であり、ownerが明示した事実・判断とは区別し、Ideaと正確な最新IdeaBriefを参照する。内部candidate-manifest validatorは、最新BriefのID・revision・Markdown fingerprintに結び付くbounded候補だけを受け入れ、T-3a投影による一意な可視引用または曖昧でない正規章を根拠位置として解決する。`brief_hypothesis`候補はEvidenceを持たず、`external_evidence`候補は選択章へ登録済みのactiveかつsource-groundedなEvidenceだけを参照できる。候補IDは同じBrief版・根拠位置・関係内容から決定的に生成し、再送時に変わらない。T-5 MCP入口は3つのBrief保存ツールで任意の`relation_candidate_manifest`を受け付ける。raw inputは`{version: 1, idea_id, candidates}`で、呼出し側はサーバー生成Brief ID、revision、Markdown hashを指定しない。入口は保存対象Ideaとの一致と64 KiB上限を確認し、validatorは保存後の正確なBrief ID・revision・Markdown fingerprintへ候補を結び付ける。

`REUSES`はIdeaからAsset、または別のIdeaへ向けられる。Idea→Ideaの`REUSES`は過去の案を新しい案の中で再利用することを表し、再利用する要素が別Assetノードとして登録されていない場合にも使える。`DERIVED_FROM`は案の由来・派生元を表し、既存案を材料として再利用することとは区別する。その他のendpoint組み合わせは各predicateのdomain allowlistに従う。

同じ保存呼出しのPhase 1ではBrief、write receipt、pending GraphJobを原子的に保存し、レポート本文を候補エラーで失わない。commit後のPhase 2は対象jobだけをclaimし、最新Idea/Brief/Evidenceを検証した候補payloadを`persist_candidate_manifest`で永続化してからRelationAssertion適用へ進む。payloadは候補ID、node ID/kind、predicate、basis、Evidence ID、Brief binding、根拠offset/章indexだけを保存し、quoteやレポート本文を複製しない。`relation_candidate_manifest`省略時はjobを未評価の`pending`として残し、`candidates: []`は候補なしを明示レビューした結果として完了させる。receiptはGraphJobの`pending`/`leased`/`succeeded`/`failed`/`superseded`状態（または状態を取得できない場合の`unavailable`）を示し、候補適用済み件数を推測して表示しない。候補検証・適用が失敗してもBriefとreceiptは残し、GraphJobの状態とsafe error codeを真実どおり返す。

Given: 3つのBrief保存ツールにboundedな候補manifestが同じIdea IDで渡される。When: Markdown付きBriefを保存する。Then: Briefとpending GraphJobはPhase 1で保存され、対象jobのPhase 2で検証済みかつquoteを含まないpayloadが保存され、receiptは適用完了を主張しない。

Given: 候補manifestのvalidationまたは適用が失敗する。When: Brief保存呼出しが完了する。Then: 保存済みレポートとwrite receiptは残り、GraphJobはpending、failed、superseded、または状態を取得できない場合のunavailableを返す。

下書きと`prior_research_import`ではCampaign Runを要求・捏造せず、外部事実とBrief由来の仮説は別basisとして読み手にも示す。

RelationAssertionは支持箇所のlocatorとして任意の`based_on_brief_revision`、`based_on_brief_quote_start`、`based_on_brief_quote_end`を保持できる。offsetは当該BriefのMarkdownにおけるUnicode文字位置の半開区間で、引用本文はRelationAssertionへ複製しない。読取時はowner・現行Idea・最新かつ共有可能なBriefとrevisionを再検査する。quoteはoffsetが一意で可視、章対応が曖昧でない場合だけMarkdownから短く復元し、失敗時は返さない。旧payloadでlocatorがないものも読み取り可能とし、保存時にquoteを推測しない。

IdeaBriefが新しい版へ進んだ場合、旧版を参照するRelationAssertionは削除せず、検索・読取から隠す。新しい関係は現行Ideaと最新IdeaBriefだけを参照する。

`assertion_family_id`は同じ主語、predicate、目的語の訂正系列を表す。訂正時は旧assertionを書き換えず、同familyでrevisionを一つ増やし、SUPERSEDESで直前版に接続する。

predicate allowlistの初期値は次とする。

- REUSES
- ADDRESSES
- DERIVED_FROM
- WORKS_AT
- HAS_CAPABILITY
- REQUIRES_CAPABILITY
- CAN_CONTRIBUTE_TO
- INTRODUCED_BY
- CLASSIFIED_AS
- EVALUATED_BY
- BASED_ON
- SERVES
- COMPETES_WITH
- DEPENDS_ON
- MERGED_INTO

Lunaはpredicate候補を生成できるが、allowlist外の値を保存できない。CAN_CONTRIBUTE_TO、INTRODUCED_BY、MERGED_INTOは本人確認前にconfirmedへできない。

## 構造edge

構造edgeはアプリが決定的に作成し、Lunaへ選択させない。

| Edge | From | To | 制約 |
| --- | --- | --- | --- |
| OWNS | OwnerProfile | 全owner node | 同じownerのみ |
| HAS_REVISION | anchor | EntityRevision | 同じentity_idのみ |
| CURRENT_REVISION | anchor | EntityRevision | anchorごとに一件 |
| HAS_SOURCE_REVISION | Source | SourceRevision | revision連番 |
| CURRENT_SOURCE_REVISION | Source | SourceRevision | Sourceごとに一件 |
| HAS_CHUNK | SourceRevision | ContentChunk | ordinal一意 |
| EVIDENCE_FROM | Evidence | SourceRevision / ContentChunk | 一つ以上 |
| HAS_AUTHORIZATION | ResearchCampaign | CampaignAuthorizationSnapshot | 有効なcurrent許諾は一件 |
| HAS_RUN | ResearchCampaign | ResearchRun | 同じauthorization系列 |
| USES_SOURCE | ResearchRun | SourceRevision | input snapshotに含まれる版のみ |
| PRODUCED | ResearchRun | ReportVersion | ReportVersion.campaign_idとRun.campaign_idが一致 |
| HAS_SECTION | ReportVersion | ReportSection | section_id 0-7を各一件 |
| REFERENCES_CLAIM | ReportSection | Claim | 章で使用したClaimのみ |
| CITES | ReportSection | Evidence | 章の引用対応があるEvidenceのみ |
| GOVERNED_BY | OwnerProfile | InstructionArtifact | 有効なcurrent revisionのみ |
| HAS_ATTACHMENT | SourceRevision | Attachment | hash一致 |

`claim_ids`、`evidence_ids`、`run_ids`、`sources`の配列はschema v1互換のread projectionに限定する。schema v2の正本は構造edgeとし、互換配列とedgeが一致しないwriteを拒否する。

schema v1の`ResearchMaterial`は新規writeに使わない。独立した資料はSource + SourceRevisionへ、引用範囲はContentChunkへ変換し、旧IDはmigration mappingに残す。

## 名寄せとmerge

PersonとOrganizationの自然キーをIDにしない。氏名、会社名、メール、電話は変更または共有されるためである。

名寄せは次の二段階にする。

1. 決定的候補生成: 正規化メールhash、E.164電話hash、名刺content hash、同一locatorを使用する。
2. Luna候補順位付け: 氏名、所属、役職、会話文脈のshareable projectionだけを使用する。

自動mergeは禁止する。本人がmergeを確定した場合、勝者anchorを残し、敗者anchorをarchivedへ変更し、confirmedのMERGED_INTO assertionを作る。旧ID、revision、関係、根拠は削除しない。検索と新規relationは勝者へredirectする。

## privacyと保存場所

| データ | 保存場所 | 検索 | MCP投影 |
| --- | --- | --- | --- |
| anchor ID、status、kind | Neo4j property | 対象 | policy適用後に可 |
| revisionの短い表示field | Neo4j property / payload | 対象 | allowlist fieldだけ |
| 長文原本、binary | local content store | local index経由 | explicit許諾時だけ |
| email、電話、住所、private note | encrypted local contentまたはlocal_only revision | hash候補生成だけ | 既定で禁止 |
| content hash、locator hash | Neo4j property | 対象 |本文を含めず可 |
| model prompt原文 | 保存しない | 対象外 | 禁止 |
| prompt version、model snapshot | AuditEvent / provenance | 対象 |必要最小限 |

fieldにpolicyがない場合はlocal_onlyとして扱う。node単位policyだけで外部投影を決めず、field allowlistを必須にする。

## Graph RAG検索契約

検索は全文と多言語embeddingの候補を合わせ、現行の意味関係と根拠経路を付けて、ローカルの多言語rerankerで順位を整える。モデルと取得件数などの実行設定は現行コードを正本とし、この文書に固定値を複製しない。

owner、現行状態、削除状態、共有区分で候補と返却項目を制限する。直接一致と関係経路を失わず、改訂・監査用の構造edgeを事業上の関連性に数えない。原文や非公開連絡先は共有可能な投影へ混ぜない。embeddingは再生成できる派生索引であり、正本の内容や根拠を置き換えない。

## 削除契約

- 通常操作はsoft deleteだけを公開する。
- deleted anchorとそのcurrent revisionは通常検索、MCP、現行レポート生成から除外する。
- 過去ReportVersionは削除せず、参照元を`unavailable`としてhash、取得時刻、削除時刻を表示する。
- Attachmentの物理削除は、参照countが0、backup policyを満たす、impact previewを本人が確認した場合だけ別commandで実行する。
- 物理削除commandをMCPへ公開しない。

設計に至る経緯と完了した検査の詳細はGit・PR履歴を参照する。旧fixture件数、未実施扱いのタスク表、旧モデルを使う検索案は現行契約に含めない。
