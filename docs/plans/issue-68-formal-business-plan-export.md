# Issue #68 フォーマル事業計画書 export 計画
最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

要望: Kadode標準のフォーマル事業計画書を、ユーザー編集可能なDOCXと提出向けPDFへ出力する内容契約とtemplate adapter境界を先に定義する。

ゴール: 5観点、財務、実行計画、根拠を同じ契約で追跡し、未確定事項と出典・更新日・ライセンス確認を成果物へ明示できる設計を後続実装へ渡す。

成功指標: 後続実装者がDOCX/PDFの入力、未確定表示、編集境界、template adapter、privacy/attribution境界をこの文書だけで検証できる。

## ユーザーストーリーと受け入れ条件

### US-68-01 標準内容を確認するユーザー

As a business-plan owner, I want five business-seed perspectives, financial assumptions, an execution plan, and evidence in one export contract, so that a formal plan remains traceable.

Given: 5観点の各入力、#65の財務仮説、#66の実行計画、根拠IDがowner space内に存在する。
When: export用の内容契約を評価する。
Then: `overview`、`customer_problem`、`market_competition`、`solution`、`execution`の5観点、`financials`、`evidence`が各source IDとともに保持される。

### US-68-02 未確定事項を識別するユーザー

As a plan reviewer, I want unresolved questions and assumptions visible before export, so that an unfinished plan is not presented as a confirmed submission.

Given: owner判断待ち、未入力、出典未確認、または更新期限超過の項目がある。
When: DOCXまたはPDFのexport preview contractを生成する。
Then: 各項目に`status=unresolved`、理由、確認者、確認期限が表示され、確定済み項目と区別される。

### US-68-03 DOCXを編集するユーザー

As a business-plan owner, I want an editable DOCX with stable headings and placeholders, so that I can revise wording before submission.

Given: export contractがownerの認証境界で検証済みである。
When: DOCX adapterを選択する。
Then: 見出し、表、注記、source locator、更新日、未確定表示が編集可能なDOCX content modelへ変換され、原本や権限情報は本文へ出力されない。

### US-68-04 提出用PDFを確認するユーザー

As a business-plan owner, I want a formal PDF snapshot, so that a fixed review artifact can be shared after my confirmation.

Given: DOCX相当の内容がownerにより確認され、未確定事項が明示されている。
When: PDF adapterを選択する。
Then: ページ順、見出し、財務単位、根拠locator、生成日時、注意書きが固定snapshotとして保持され、編集用metadataは本文へ出力されない。

### US-68-05 公式様式を検討する責任者

As a product owner, I want official-form references isolated behind an adapter, so that a stale or unauthorized copy cannot become the product template.

Given: 日本政策金融公庫を含む公式様式を将来候補として比較する必要がある。
When: template source reviewを開始する。
Then: source URL、発行者、確認日、更新日、利用条件、差分を記録し、実ファイル取得・無断転載・固定化をせず、adapter interfaceだけを計画する。

## 内容契約

| section | 必須内容 | 状態・根拠 |
| --- | --- | --- |
| `overview` | 事業名、目的、要約、対象owner | owner入力、未確定表示可 |
| `customer_problem` | 顧客課題、背景、匿名化済み根拠ID | raw個人情報を含めない |
| `market_competition` | 市場仮説、直接・間接・代替競合、潜在参入リスク、勝ち筋/機会の本人判断 | #64の根拠/AI推論/本人判断を分離 |
| `solution` | 提供価値、提供手段、検証仮説 | 未検証仮説を明示 |
| `execution` | #66の週次時間、家計資金上限、small experiment、撤退条件、resource、roadmap | 金融機関推薦を含めない |
| `financials` | #65のprice、variable cost、contribution margin、CAC、retention、fixed cost、capacity、period、base/upside/downside | Decimal、通貨、期間を併記。会計・税務助言ではない |
| `evidence` | source ID、revision、locator、発行者、確認日、更新日、license status | owner許可済み参照のみ |
| `uncertainties` | unresolved項目、理由、確認者、期限 | export前に隠さない |

## Adapter境界

`FormalPlanContent`はKadode標準の中間契約とし、`DocxTemplateAdapter`と`PdfSnapshotAdapter`はこの契約だけを受け取る。adapterは内容の計算、owner認証、根拠の取得、未確定事項の解消を行わない。

将来の公式様式adapterは`TemplateSourceDescriptor {issuer, source_url, checked_at, published_at, license_status, version}`を受け取り、公式ページの最新版確認結果だけを記録する。日本政策金融公庫を含む候補の実ファイルを取得・保存せず、様式本文を複製しない。採用時は専用ADRと出典確認スパイクを先行させる。

## Privacy / attribution境界

- export入力は固定owner principalから取得し、request bodyのowner IDを信頼しない。
- 個人情報、raw customer interview、銀行口座、残高、認証情報、外部AIへの入力を成果物へ含めない。
- 根拠は匿名化済みEvidence ID、source revision、locator、発行者、確認日、更新日だけを出力する。
- 公式様式の利用条件と出典を注記し、無断転載と古い様式の固定化を防ぐ。

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| Q-68-01 | DOCX/PDFの目次、用紙、フォント、ページ番号をどの標準へ固定するか | プロダクト責任者 | 実export PR開始前 |
| Q-68-02 | 公式様式adapterのlicense statusを誰が承認し、何日ごとに再確認するか | CEO/法務責任者 | template adapter実装前 |
| Q-68-03 | 未確定項目が残る場合の提出禁止または警告表示をどの状態遷移で決定するか | CEO/プロダクト責任者 | export UX実装前 |

## スコープ外

- UI、App.jsx、WorkspaceShell、frontend/backend API、PDF/DOCX実生成。
- 公式サイトへの接続、実ファイル取得・保存、公式様式本文の転載・固定。
- 外部検索、外部AI、Supabase実接続、個人情報送信、実課金。
- 税務、会計、融資、法務の判断または提出可否の保証。
- #89/T-IA-03の変更、匿名化器、同意取得、owner/RLS実装。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-68-01 | `FormalPlanContent`と未確定状態のschemaを実装用に分解 | 検査: 5観点・財務・実行・根拠・uncertaintiesが内容契約表と一致 | 既知 |
| スパイク T-68-02 | 公式様式の出典・更新日・license確認方法を決定 | 検査: Q-68-02の承認者、確認周期、adapter入力をADRへ記録 | 既知 |
| T-68-02 | template adapter interfaceとprivacy/attribution境界を実装PRへ転記 | 検査: adapterが認証・取得・計算を行わない契約テストを追加 | 類推可能 |
| スパイク T-68-03a | DOCX/PDFレイアウトと未確定表示の決定 | 検査: Q-68-01、Q-68-03を決定し、内容契約のfixtureへ反映 | 既知 |
| T-68-03 | レイアウト決定後にDOCX/PDF出力fixtureを分解 | 検査: 未確定表示、根拠属性、ページ構造を形式別契約テストへ転記 | 未知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| 中間契約 | `FormalPlanContent`を唯一のadapter入力にする。DOCX/PDF間の内容差を防ぎ、計算と表示を分離する。 | DOCX/PDFごとに個別payloadを作る案は未確定表示と根拠が分岐するため却下。 | 1契約から2形式へ変換する。 |
| template境界 | 公式様式は`TemplateSourceDescriptor`で出典・更新日・licenseだけを保持する。 | 公式ファイルをrepositoryへコピーする案は無断転載と陳腐化リスクがあるため却下。 | 採用判断と取得は後続の承認済みadapterへ隔離する。 |
| 未確定表示 | `status=unresolved`と理由・期限をDOCX/PDF双方へ出力する。 | 未確定項目を空欄または削除する案は提出者が欠落を検知できないため却下。 | export前に確認状態を観測できる。 |
| 根拠とprivacy | 匿名化済みID、revision、locator、出典属性のみを出力する。 | raw本文・個人情報を注記へ含める案は外部共有時の漏えい境界を越えるため却下。 | attributionを維持しつつ本文を非開示にする。 |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | Issue #68 planning first sliceを新規作成 | フォーマルDOCX/PDF内容契約と公式様式adapter境界を先行定義 | T-68-01〜T-68-03 |
