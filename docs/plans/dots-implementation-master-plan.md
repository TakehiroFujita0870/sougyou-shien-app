# Dots 実装全体計画

最終更新: 2026-09-26
現行実行状態: 2026-09-26の「では進めていいですよ」により再開済み。以下の待機に関する時点記録より、この状態を優先する。
実装開始条件: 2026-09-26、利用者の「では進めていいですよ」で再開。下書き→許諾済み調査→正式な意味分割の追補を含むRP計画を実行する。一般公開・安全保護回避・保存データ削除は許可されていない。不要な検証用登録の解除は正本の全受入完了後に限る。
進捗記録: [`dots-execution-ledger.md`](../operations/dots-execution-ledger.md)。現行の配送状態は下記の配送順を優先する。PR #246–259をmainへ反映済み。通常接続では下書き→許諾済み調査→根拠付き概要・意味関係保存→別会話の新規検索を1組確認し、正確な関係ID・状態・根拠IDも一致した。一方、代表5組・訂正後再利用・Neo4j実同時保存・歴史的許諾の証明・スマホ拒否後の書込み・本人限定の最終監査・残差分の配送・最終起動は未完了。MVP完成とは扱わない。再開前の記録は[`dots-mvp-completion-2026-09-25.md`](dots-mvp-completion-2026-09-25.md)を参照する。
残変更の配送順: [`dots-mvp-delivery-packets-20260926.md`](dots-mvp-delivery-packets-20260926.md)。古いlive基点の大量差分を一括配送せず、清潔なmain基点から目的別に選別する。完成条件はこの分割では縮小しない。
製品要件正本: [`founder-graph-pivot.md`](founder-graph-pivot.md)
データモデル正本: [`founder-graph-data-model.md`](founder-graph-data-model.md)
Graph RAG read計画: [`founder-graph-read-2hop.md`](founder-graph-read-2hop.md)
ローカルGraph RAG計画: `founder-graph-local-graphrag.md`（作業ツリーにある詳細資料は未配送。現行要件は本書を正本とする）
schema v2移行計画: [`founder-graph-schema-v2-migration.md`](founder-graph-schema-v2-migration.md)
schema v2 parity計画: [`founder-graph-v2-parity.md`](founder-graph-v2-parity.md)
名寄せ候補評価計画: [`founder-graph-namesake-evaluation.md`](founder-graph-namesake-evaluation.md)
Graph UI live read計画: [`founder-graph-live-ui-read.md`](founder-graph-live-ui-read.md)
ローカル操作盤・背景起動計画: `founder-graph-local-control-dashboard.md`（詳細資料は未配送。現行要件は本書を正本とする）
根拠付き関係保存計画: [founder-graph-relationship-evidence-write.md](founder-graph-relationship-evidence-write.md)

## 要望 / ゴール / 成功指標

要望は、次の指示だけでDotsの初期完成範囲を自律実行できる状態を作ることである。

> Dotsの実装全体計画を完遂するまで自走する。Codexのsubagentは利用者の指定に従いGPT-6 Luna Mediumを使い、独立タスクを最大三つ並列実行する。Dots製品内の検索embeddingとrerankにはSentence Transformers対応のローカル多言語モデルを使う。root coordinatorは計画、依存、所有権、検査、PR、判断境界の統制へ集中する。

ゴールは、ChatGPTで生まれたアイデアをローカルDotsへ保存し、DotsとNeo4jを停止・再起動した後も検索でき、本人の資産、人脈、根拠、調査履歴、8章レポートへ接続できる単独利用Founder Graphを完成させることである。

成功指標は、WindowsへログインすればDotsとChatGPT接続が利用可能になり、代表会話5件でアイデアを保存・再検索し、過去の人物・資産・根拠へ結び付けられること。これに加え、複数ResearchRun、訂正、名寄せ候補、backup / restore、soft delete、Graph UIを合成データで検証し、実データ投入前security gateを通過する。

## 2026-09-26 再計画: 再開後の作業正本

### 継続実装の受け入れ境界

- 起動準備: tunnel serviceのactiveだけでは利用可能としない。既存の120秒全体期限内で、公開health/readyとcontrol-plane pollを確認してから準備完了とする。固定待ち時間の追加で代替しない。画面の接続状態も同じ確認に基づき、確認不能は停止/不明として表示する。通常DBはこの修正の検査のために停止しない。
- 可逆削除: owner固定の内部Source/Idea操作に限定し、既存ARCHIVED状態と保存境界のrevision照合・再送保護を再利用する。元状態の復元情報は本文を含まない永続記録へ残す。一般ノード削除、物理削除、新しいMCP削除機能、管理UI追加は今回の対象外。
- 削除後の読み取り: archived SourceのRevision/Chunk/Evidence、archived Ideaの改訂/概要/関係を通常検索・fetch・経路・安全なexportから隠す。兄弟記録は隠さない。Report/Run/監査履歴は保持し、参照先が非現行ならReportは本文なしのunavailableを返す。復元時は元状態へ戻し、全参照が現行の場合のみ再表示する。memory/Neo4jで同じ拒否・再送・表示条件を検査する。
- 復旧受入: 同一の隔離合成fixtureで削除、export、Neo4j backup、別保存先restore、復元操作を照合する。manifestにattachments未構成・未収録を明記する。今回の合格はNeo4j-onlyであり、将来の添付有効化や旧P8製本実装の完了を意味しない。通常データの削除は行わない。
- RP07隔離検証記録（2026-09-26）: `backend/tests/test_founder_graph_rp07_recovery_real.py` の改訂後、Neo4j 5.26の匿名volumeを使う同一合成fixtureでsafe export/manifest、Source削除時のEvidence非表示・Report本文なし、offline `neo4j` database dump/load、別container起動後のAPI読戻しを確認した（opt-in実DB test 1 passed）。再起動後はhost portを再取得してURIを組み立て、前後のportを一時recovery manifestに記録する。旧削除key replayが既復元のReport可視状態を保ち、新key+現revisionで再削除した後も旧restore key replayは状態を戻さず、新key+現revisionのrestoreで再表示する。失敗時はcontainer state/exit code/OOM/healthと、raw logを含まない安全なerror classだけを取得する。添付は未構成・未収録 (`attachments.configured=false`, `included=false`)。この検証はNeo4jの`neo4j` databaseのみであり、system database / users / rolesや旧P8製本を含むfull DBMS archiveの完成とはしない。通常DB/サービスは対象外。

この節と末尾のDefinition of Doneを現行の残作業の正本とする。後続の旧phase表・測定値・時点別未完了一覧は履歴と設計inventoryであり、そのまま再実行しない。全体完成を「初回検索の解消とGit反映の2件だけ」と説明した以前の報告は取り消す。

### 要望 / ゴール / 成功指標

要望原文: 「スマホからは参照はできたみたいだけど『Dotsへの書き込みが安全性チェックでブロックされた』」「グラフのページを開いた後に別ページに遷移するとホワイトアウト」「内容から関係候補を抽出し、根拠とともに保存して、次の会話で実際に再利用できることをMVPの中心的な完成条件に据える」「実装の全体計画をリバイス」「着手は待って」。

ゴール: 本人がChatGPTで話した創業アイデアと資産を、内容の関係と根拠を持つ知識グラフとして蓄積し、別会話で再利用でき、PC画面と本人用接続が安全に継続動作するMVPを完成させる。

成功指標: 保存件数や履歴edge数ではなく、代表5会話の保存→意味関係→別会話検索→組合せ提案を観測し、全関係で根拠・推測区分を追跡できる。スマホからの参照は利用者報告として確認済み扱いにするが、書込みは失敗中とする。スマホ用Dots管理画面は作らない。

### 2026-09-26 追補: 下書き→調査→正式な意味分割

要望原文: 「調査が終わったものを意味分割した方が良い」「調査していないアイデアも下書きとして保存・検索できる」「一連の実装が終わったら要らない検証用プラグインはツール一覧から削除」「正本のDots.だけ私から見えるように」。

この追補は旧phaseと他計画の調査前グラフ化・レポート保存手順に優先する。2026-09-26の明示再開指示後に実行する。

1. ChatGPTで語られたアイデアを、原文の出所と題名・短い概要を持つ下書きとして保存する。調査許可は保存の前提にしない。下書きも通常検索に含め、画面と返却結果に未調査と表示する。
2. 調査前はDots内の過去案・資産・根拠を検索する。検索語の整理と暫定候補は許すが、下書きから顧客・課題・提供価値の正式な意味ノード/関係を自動確定しない。検索用chunk/embeddingは正式な意味分割と区別する。
3. 目的・範囲・試行予算の許諾後、ChatGPTが調査し、指定8観点の評価と洗練されたアイデア概要をまとめる。調査中断・拒否・失敗でも下書きを保持し、調査済みと表示しない。
4. まとめた概要と評価から顧客・課題・提供価値・必要な能力・関連資産・過去案を抽出し、既存概念を照合する。Dotsへ根拠と推測区分を持つ関係候補を保存する。「調査済み」は「事実として確認済み」と同義にしない。人の統合には本人確認を残す。
5. 次の会話で下書きと調査済み案を検索でき、後者は意味関係と根拠をたどれる。追加調査で概要が改訂されたら影響する意味関係を更新し、旧根拠/旧関係を履歴に残す。再送で重複を作らず、意味分割失敗時は概要を失わず未処理状態を示す。

Dotsのホームでは洗練された概要を中心にする。調査レポート全文の常設閲覧・製本はMVPの必須条件にしない。再利用・訂正のための引用、出所、評価、版情報は保持する。資産の自己紹介整理は調査完了を前提にせず、この順序変更は事業アイデアに適用する。

#### US-RP-08 下書きを残し、調査後に正式な意味分割を行う
As a 本人, I want 未調査のアイデアも残し、調査後の概要をグラフ化したい, so that 思いつきを失わず途中の仮説で検索を汚さない。
Given: 新しい下書き、既存の関連資産、許諾後の8観点評価と概要がある。
When: 保存→内部検索→許諾→調査→概要保存→意味分割を行い、調査中断・意味分割失敗・追加調査・再送も試す。
Then: 未調査の下書きは別会話から検索でき、調査前の正式な意味関係自動作成は0本。調査後の関係は概要の版と根拠へ到達でき、推測を事実化しない。失敗時に下書き/概要を失わず、訂正後は旧関係を現行検索から除外し履歴に残し、再送重複は0件となる。

#### US-RP-09 完了後は正本のDotsだけを使う
As a 本人, I want ツール一覧で正本のDotsだけを選びたい, so that 検証用保存先と取り違えない。
Given: 正本接続、検証用接続、補助プラグインとそれぞれの保存先の対応表がある。
When: 正本で全受入試験を終え、不要な検証用登録をツール一覧から解除する。
Then: PCとスマホの本人ChatGPTで見えるDotsの選択項目は正本1件だけとなり、その1件から通常保存先への保存・検索が成功する。必要な補助機能は正本へ統合するか依存を解消してから解除する。保存データ、通常DB、復旧用コピーは削除しない。

追加タスク（全行を現行タスク表と同じ実行対象とする）:

| ID | 依存 | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- | --- |
| RP-04D | RP-SP-04の結論 | 下書き状態・調査後の正式意味分割・改訂時更新を最小保存経路へ接続。RP-04と同一所有者が時分割で実施 | 検査: US-RP-08。既存schemaで表せない場合は実装前に影響を記録し計画へ差し戻す | 類推可能 |
| RP-11 | RP-10,US-RP-08の成功 | 接続/プラグイン依存一覧の照合と不要な検証用登録の解除、利用手順更新 | 検査: US-RP-09。正本1件の機能維持を読戻し確認し、解除対象IDと再登録手順を記録。保存データの削除は対象外 | 類推可能 |

完了条件への追加: US-RP-08とUS-RP-09の成功を必須とする。RP-SP-04は調査後の期待graphを作り、RP-04は調査後概要を入力にする。RP-05/06/08/09/10はRP-04D完了を追加依存とする。従来のUS-RP-04の「5会話」は、各会話の許諾済み調査結果と概要を含むfixtureとして検証する。初期下書きだけのgraph生成を合格に数えない。

ADR: 調査後の洗練された概要を正式な意味分割の入力とし、調査前は下書き保存と内部検索に限定する。調査前から全仮説を正式グラフへ追加する案は検索の混濁と更新負担が大きいため却下する。下書きを保存しない案は思いつきを失うため却下する。検証用登録は正本の受入完了後に解除し、先行解除で試験経路や必要な補助機能を失う案を却下する。

変更履歴: 2026-09-26、利用者の順序変更と検証用登録整理を反映。影響: RP-SP-04/RP-04〜10、追加RP-04D/RP-11、US-RP-08/09、全DoD。今回は計画文書だけ変更し、実装・登録解除・Git公開は開始しない。

### 診断表（追補前の確認結果）

| 項目 | 確認できたこと | 未確定・残検査 |
| --- | --- | --- |
| スマホの書込み拒否 | 利用者の会話「登録できます」を本文とChatGPT UIで読んだ。資産登録の明示依頼に対して検索成功・一括登録拒否・分割再試行拒否という説明がある | ChatGPTの実際の拒否コード、ツール名・引数、確認画面の有無は取得できていない。説明文だけでMCP書込み実行や拒否元を断定しない。原文や個人生活情報はfixture/Gitへ転載しない |
| MCP安全属性 | stdioのtools/listはreadOnlyHintだけを返す。現行公式referenceはdestructiveHintとopenWorldHintも要求している | metadata不足は不具合候補だが、今回の拒否原因と確定していない。stdio/FastAPI/登録済みcatalogの一致とhost判断を照合する |
| ホワイトアウト | PC 1280×720でホーム→グラフ→ホームを再現。pageerrorは`stopAnimation is not a function`、nav button 0、body文字数0。インストール済み3d-force-graphの公開APIはpauseAnimationで、stopAnimationは存在しない | 修正は未着手。描画解放、非同期import完了前の遷移、連続遷移、例外封じ込めを含めて検査する |
| 意味グラフ | 通常UI APIはIdea 6、Source 3、SourceRevision 3、ContentChunk 1。edge 7本はCURRENT_SOURCE_REVISION 3、HAS_SOURCE_REVISION 3、HAS_CHUNK 1のみ | 内容上の意味関係は0本。Facet保存・探索部品の合成試験成功は、会話からの自動抽出成功を意味しない |
| 本人用アクセス | Compose、API、管理画面、中継管理口はloopback。一般公開の入口を作らずSecure MCP Tunnelを使用。MCPはruntime固定ownerを使い、入力のowner指定は許さない | OpenAI側の現行workspace/organization関連付け・メンバー・アプリ共有状態を全件照合していない。固定ownerはデータ境界であり、呼出者の本人認証ではない。鍵保持者・本人アカウントの利用者・同一PCのlocal processを信頼する境界を記録する |
| 初回検索504 | 中継再起動後の最初の検索が504、直後の再試行は成功。モデル事前準備を追加しても残った | ローカル準備完了、上流request到達、session、transportを分離する。待ち時間の追加や根因未確定のwarmupを完了解消として扱わない |

参考: [OpenAI tool annotations](https://developers.openai.com/plugins/reference)、[Secure MCP Tunnelの権限](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)。安全属性はhostの確認を補助するもので、serverの認可を代替しない。

### ユーザーストーリーと受け入れ条件

#### US-RP-01 本人が端末を変えて保存する
As a 本人, I want ChatGPTから資産を保存したい, so that PCとスマホで記録を失わない。
Given: 同じ本人アカウントのDots接続と、個人情報を含まない合成資産がある。
When: PCとスマホのChatGPTから同じ意味の明示保存を行い、別会話で取得する。
Then: 許可された記録だけ保存され、返却IDと保存結果が一致する。拒否時は拒否元と実保存の有無を区別し、勝手な再試行や重複保存をしない。スマホ側の仕様制約なら、その制約と本人が取れる操作を示す。

#### US-RP-02 本人以外へ公開しない
As a 本人, I want 接続できる相手を把握したい, so that 私的記録を第三者へ渡さない。
Given: 現行の個人アカウント、organization/workspace、接続と秘密ファイルがある。
When: 関連付け・権限・公開範囲・OSファイル権限を読み取り監査し、許可の無いcallerのnegative testを行う。
Then: 一般公開0、意図しないメンバー/共有0、owner越境0を確認し、同一PCや本人sessionを利用できる人は別途信頼境界だと明記する。確認不能な経路を「本人のみ」と断定しない。

#### US-RP-03 グラフから離れても画面を使う
As a 本人, I want グラフと他画面を行き来したい, so that F5で回復する手間をなくす。
Given: PC 1280×720で3Dグラフを開ける。
When: graph→homeとgraph→servicesを各10回、描画中・読込中・失敗時に遷移する。
Then: pageerror 0、画面全体の空白0、遷移先の内容とnavが残り、グラフのanimation/listener/canvasが解放される。描画例外があってもナビゲーションは残る。

#### US-RP-04 内容から意味の関係を蓄積する
As a 本人, I want 発言の内容から資産とアイデアの関係候補を保存したい, so that 次の案を考える材料が育つ。
Given: 架空の5会話に、顧客課題、Idea、Asset、協力候補、根拠発言と無関係な記述が含まれる。
When: 既存記録を照合し、内容から抽出したentityと関係候補を保存する。
Then: 期待する意味関係を全て保存し、無関係な関係は0本、根拠被覆100%、根拠のない確定0、再送重複0を確認する。単なる履歴edgeや文章の近さを意味関係の成功数へ算入しない。人の統合は本人確認を残す。

#### US-RP-05 別会話で意味関係を使う
As a 本人, I want 過去案と自分の資産を掛け合わせたい, so that 新しい事業案を検証できる。
Given: US-RP-04の知識グラフと、独立した期待結果5組がある。
When: 新しいChatGPT会話で言い換えたqueryを送り、関連資産・人物・過去案を探す。
Then: 5組すべてで期待する記録を上位5件へ含め、関係path・根拠・推測状態を保持し、提案がその根拠を参照する。再起動後もIDと意味関係が一致する。検索速度の比較は行わない。

#### US-RP-06 意味のグラフを表示する
As a 本人, I want 事業内容と資産のつながりを眺めたい, so that 履歴ではなく組合せを発見できる。
Given: 根拠付き意味関係と分類階層がある。
When: グラフで抽象領域を選び、スクロールで奥へ進む。
Then: semantic entity/edgeを主役に表示し、SourceRevision/Chunk/監査/版管理は通常表示から除外する。推測と確定を区別し、根拠へ到達でき、無関係な領域を混ぜない。3D物理演算と手前奥の階層を維持する。

実装契約（2026-09-26監査追記）: 現状のraw relationship一覧は保存構造の表示であり、US-RP-06達成とは扱わない。owner限定の現行RelationAssertionを端点間の`semantic_edges`へ投影し、`id/source_id/target_id/predicate/status/confidence/evidence_ids/based_on_brief_id/based_on_brief_section_index`を返す。旧関係・削除済み端点を除外し、Evidence IDは共有可の既存参照だけとする。本文・source/raw payloadは返さない。通常画面ではassertionの中継ノードとASSERTS_FROM/ASSERTS_TO/EVIDENCED_BY等の足場を意味関係として描かず、意味・推測状態・根拠ID・概要の版と章を選択時に確認できるようにする。合成の現行/訂正済み/非公開根拠を使うbackend検査と1280×720のUI検査を受入証跡とし、実会話での再利用は別途US-RP-05で確認する。

根拠への導線: ID表示だけで完了としない。既存のlocalhost制御経路に固定ownerの読取専用`GET /api/graph/semantic-edges/{assertion_id}/provenance`を加え、現行関係・両端・正確な概要版/章の一致を検査し、その章の内容と共有可能なEvidenceの`id/polarity/confidence/status`だけを返す。概要章は既存homeと同じ情報範囲で、source本文・excerpt・locator・raw payloadは追加しない。古い関係/別owner/異なるIdeaや概要章は一般化した失敗応答とする。既存loopback/Host/Origin/no-store境界と停止時の拒否を維持し、新たな外部公開やOS本人認証とは主張しない。PCで関係選択後に「根拠を確認」すると正確な章と根拠状態を表示し、失敗時は根拠未確認とする。合成route/client/componentの正例と拒否例を必須検査にする。

#### US-RP-07 MVP全体の残りを閉じる
As a 本人, I want 完成範囲と未対応を区別したい, so that 未検証の機能を信じて記録を失わない。
Given: 保存・検索・概要改訂・調査結果保存・復旧・削除・書出しの既存部品と実行証跡がある。
When: 実装/実機確認/main反映を別欄で照合し、不足している条件だけ検証する。
Then: 許諾済み複数ResearchRunと8観点改訂、合成soft delete/safe export、隔離restore、依存順起動・停止/再開、main smokeを確認する。未接続の部品を実利用可能と報告せず、全DoDが一致するまで完成にしない。

RP-08完成レポートの保存境界（2026-09-26監査追記）: `save_research_report`のFINAL ReportVersionは、全参照RunがCOMPLETEDで、開始/終了が存在し、開始が承認以後、終了が開始以後かつ現在/許諾期限以前であることを保存時に検査する。既存のowner・同一Campaign・8章・根拠・財務契約も維持する。Neo4jは関連Campaignを共通のsorted lockで照合して、取消との競合を防ぐ。同一操作再送は先に受領結果を返す。DRAFTは未完了Runの参照を許容し、完成扱いへ昇格させない。ReportVersionはIdeaBriefとは別の保存物なので、新たな概要参照を必須化せず既存の役割を保持する。FINALのpending/承認前開始/未来終了/期限超過/取消拒否とDRAFT許容を合成検査し、可能なら隔離Neo4jでも同じ境界を確認する。

### 再開後の実行順とタスク

| ID | 依存 | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- | --- |
| RP-SP-01 | 再開指示 | スマホ拒否・本人限定アクセスのスパイク。会話の拒否結果、tool catalog、安全属性、readonly server trace、権限の対応表 | 検査: host未送信/transport障害/server拒否/保存済みの4状態を区別し、原因・最小修正・未確認を記録。2時間で未確定なら調査結果を返し、保護を外さない | 未知 |
| RP-01 | RP-SP-01の結論 | 原因に限定した書込み・認可修正またはhost制約の利用手順 | 検査: US-RP-01/02。固定ownerをcaller認証と取り違えない。metadataは全tool/全transportで真の副作用と一致 | 類推可能 |
| RP-02 | 再開指示 | グラフ終了処理修正と画面例外の局所化。独立PR | 検査: US-RP-03のPC実ブラウザー試験。既存mockのみで合格にしない | 既知 |
| RP-SP-03 | 再開指示 | 初回504のスパイク。中継readyと実requestの時刻、上流到達、session再接続の照合 | 検査: 故障層を特定。2時間上限。本文/鍵をログへ追加せず、モデル準備完了だけで解消扱いにしない | 未知 |
| RP-03 | RP-SP-03の結論 | 初回接続障害に限定した修正または再接続手順 | 検査: 中継再起動後の最初のreadが3回連続成功。性能比較ではなく成功/失敗の機能検査 | 類推可能 |
| RP-SP-04 | 再開指示 | 内容抽出のスパイク。entity/relation allowlist、粒度、根拠、訂正、分類階層、MCP最小入口を固定 | 検査: 人間向け5会話の期待graphを先に作り、既存domain/Assertionで表現できるか照合。2時間上限。新schema必要時は影響を記録して計画へ差し戻す | 未知 |
| RP-04 | RP-SP-04の結論 | ChatGPTからentity・根拠・関係候補を保存する最小経路。保存先のLLM常駐jobは追加しない | 検査: US-RP-04。全payload validatorと同一要求再送を検査し、privacy/safetyを回避しない | 類推可能 |
| RP-05 | RP-04 | 意味関係を検索・再利用する実会話試験 | 検査: US-RP-05。旧固定20問を再測定せず、意味関係5組の機能確認を追加 | 類推可能 |
| RP-06 | RP-02,RP-04 | semantic graphの通常表示と根拠・推測の表示。独立PR | 検査: US-RP-06、1280×720。履歴edge数を成功指標にしない | 類推可能 |
| RP-07 | 再開指示 | 全体の受入証跡inventory。旧P0〜P9を実装/実機/mainの3欄へ照合 | 検査: US-RP-07。不足taskだけを新しいpacketにし、完了済み試験の反復を禁止 | 既知 |
| RP-08 | RP-07 | 調査結果保存・改訂、soft delete/safe export、復旧の不足条件を閉じる | 検査: US-RP-07。不足経路が未知なら先に最大2時間のスパイクを追加し、結論前に実装しない | 類推可能 |
| RP-09 | RP-01〜08 | Git所有範囲整理、意味単位commit/PR/review/main統合と通常環境への反映 | 検査: 秘密・原文・生成物・他作業0、required CI/main smoke成功。各PRは単一目的、500行以内を目安に分割 | 既知 |
| RP-10 | RP-09 | 最終本人試験と実Windows再起動確認 | 検査: 同一ID/意味path、依存順起動、画面閉鎖後の稼働、画面から停止/再開、スマホread/write可否と手順、DoD全件 | 類推可能 |

再開時はRP-SP-01、RP-02、RP-SP-04を非重複ファイルで並列化し、RP-07をcoordinatorが先に照合する。初回504は調査結果とファイル所有権に応じて次枠で扱う。Luna subagent認証401が未解消なら別モデルへ無断fallbackせず、該当scopeを止める。通常DBへ追加する試験記録は識別可能にし、削除は本人の別指示を待つ。

### 質問リスト

再開スパイクの結論: 既存Ideaはdraftを保存できるが、ホームがその状態を返していない。IdeaBriefの存在や8章の枠だけでは調査完了を証明できないため、概要があっても自動で調査済みに昇格させない。RP-04Dを次の単一目的へ分割する。

| ID | 依存 | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- | --- |
| RP-04D1 | RP-SP-04 | ホームで下書きを未調査と表示。概要の有無だけで調査済みと表示しない | 検査: local_home/LocalHomeSurfaceでdraft保持、概要付きdraft、未知状態の非昇格、従来カード操作を確認 | 既知 |
| RP-04D2 | RP-04D1,RP-SP-04 | 明示的な調査完了と概要版の紐付け、意味分割の開始条件 | 検査: 許諾済みcompleted Runと全8観点が揃った版だけ開始可能。中断/未許諾/部分概要は拒否 | 類推可能 |
| RP-04D3 | RP-04D2 | 概要版/章と根拠の紐付け、改訂時の旧関係の現行検索除外 | 検査: 同一要求再送重複0、別targetへの訂正で旧関係が履歴に残り現行検索に出ない | 類推可能 |

RP-SP-01の結論: stdioとFastAPI catalogで安全属性3項目の不足を確認。真の副作用に一致する属性補完は実施するが、スマホ拒否の根因と断定せず、登録済みcatalogとhost結果の照合を残す。

#### RP-04D2 実装契約（読み取りスパイク後）

既存domainにCampaign/Runはあるが、MCPから許諾・調査結果を記録する入口はない。Dots側に調査schedulerは加えず、ChatGPTの調査結果のwrite-backを実装する。

- Campaignは未許諾で作成し、表示済みの目的・範囲・試行予算・期限に対する本人の明示承認後にだけ別のapprove操作で許諾版を保存する。利用者からowner/authorized/status/run_countを受け取らない。承認は範囲・予算を変更しない。取消は新しい未許諾REVOKED版とし、履歴を残す。
- RunはChatGPT側の調査終了後にcompleted/partial/failed/cancelledの結果として記録する。新しいwrite port `record_research_run(run, expected_campaign_revision, idempotency_key, actor)`が、現行Campaignの許諾・期限・予算・snapshotと同一ownerを検査し、Campaignの試行数更新とRunを1トランザクション/lockで保存する。再送は同じreceiptを返し、予算を二度消費しない。外部調査実行前の試行予算確認はChatGPT側の手順で行い、この保存操作が既に行われた外部調査の費用を阻止できるとは説明しない。
- IdeaBriefへ`research_run_ids`を追加する。既存値は空で読み取れるが、空/未完了Run/未許諾/取消/別owner/別Idea/不足する8観点の概要では正式意味分割を許可しない。通常の部分概要保存は維持し、状態を調査済みにしない。確定済み概要の訂正は、最新Runと概要版を再照合する。
- 根拠のないfactを確定しない。全8観点が埋まる条件は内容の存在確認であり、主張の正しさの自動保証ではない。shareableな短い概要と、local_onlyな調査原文/入力snapshotは分離する。

追加受入条件: Given: 未許諾/許諾済み/取消/期限切れCampaignと異なるownerのRunがある。When: 許諾・結果保存・概要確定を行い、同一要求再送と途中の保存失敗も試す。Then: 許可済みの範囲でだけ保存され、Campaign更新とRun保存の片残り0、再送の予算二重消費0、未完了Runによる正式グラフ化0となる。

| ID | 依存 | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- | --- |
| RP-04D2a | ingressスパイク結論 | 完了調査概要のpure validatorとIdeaBriefのresearch_run_ids | 検査: 未完了/未許諾/取消/期限切れ/owner/Idea mismatch拒否、8観点欠落拒否、既存部分概要の保存は維持 | 類推可能 |
| RP-04D2b | ingressスパイク結論 | memory/Neo4jの原子的Run結果保存とResearchCampaign/Runの限定decode | 検査: stale snapshot/CAS/予算/再送/途中失敗、実Neo4j合成rollbackとparity | 類推可能 |
| RP-04D2c | RP-04D2a/b | Campaign作成/承認/取消、Run結果記録、調査済み概要のMCP入口 | 検査: メタデータ全transport一致、許諾gate、receipt、privacy、再送、通常部分概要からの不正昇格0 | 類推可能 |

#### RP-04D2d 出典の保存入口（2026-09-26実会話で検出）

時点記録（続報前）: 実会話でSourceを単独で取り込む入口の不足を検出し、PR #250で`capture_source`のcreate-only保存基礎をmainへ配送した（`f636fd2a8b8e`）。系譜edge・catalog属性の一致・実Neo4j fault-rollback・Source→Claim→Evidenceの隔離試験が独立承認後、通常API→health成功→stdio tunnel→control-plane poll成功の順でruntimeへ反映した。この時点では通常ChatGPTの出典保存と通し再利用は未了だったが、下記の続報で1組成功を確認した。Idea保存の会話原文を研究資料として代用したり、公開資料を架空のAssetへ変換して合格にしてはならない。`capture_evidence`が要求するSourceRevision/ContentChunkをChatGPTが正規の入口から先に保存できることをRP-04D3と実会話受入の追加依存とする。

配送済み追加依存（2026-09-26読取監査、PR #252）: 以前の`append_claim`は共有範囲を指定できず既定のlocal_onlyとなり、Idea→Claimの関係を保存できてもMCPで再利用できなかった。新規Claimに限ってlocal_only/shareableを明示する閉じた入力を追加・検査・独立承認後に反映済み。省略時は非公開、既存Claimの共有範囲は変更しない。research_allowed等は許可せず、Source/Revision/Chunkの非公開は維持する。許諾済みの公開出典に基づく短い事実文だけをshareable試験に用い、読取項目と関係端点の共有検査を保持する。残る完成条件は代表5組・訂正後再利用・正式関係経路の全main配送であり、この共有指定を再実装しない。

- Given: 公開出典のURL・資料名・自作の短い要約があり、本人がその資料を保存する範囲を許諾している。
- When: owner固定の資料保存機能を呼び、返却された実Chunk IDと別途保存した実Claim IDでEvidenceを記録する。
- Then: Source/不変Revision/Chunkが原子的に保存され、再送で重複しない。受領結果には識別用IDのみを返し、本文・原文・URL等の場所情報は既定でlocal_only。既存のSource系譜・共有境界・再送契約を再利用し、owner、状態、RevisionやChunk IDを呼出側に捏造させない。
- 検査: 公開一覧/annotations/schemaのtransport一致、memory/Neo4j保存parity、途中失敗rollback、同一番号の内容変更拒否、非公開本文非漏洩。実ChatGPTで出典→Claim→Evidence→許諾済みRun→8観点→正式関係→別会話再利用を確認するまで完了にしない。
- 外部資料の自動取得、添付ファイル取込、Assetの自動創作、新規公開範囲の拡大は対象外。既存記録を削除せず、追加機能を止めれば戻せる。

ADR: ResearchRunは既存のimmutable terminal記録として1回保存し、Campaign更新と同時に行う。別々のput_nodeは片残りと予算二重消費を生むため却下する。研究完了を概要文章だけから推測する案を却下する。調査完了情報はpayload参照の追加で表現し、新しいNeo4jラベル/制約は作らない。

2026-09-26実会話の続報: 上記の出典保存未了という時点記録に対し、通常ChatGPTからSource2件、Claim/Evidence各2件、completed Run、全8観点の概要、根拠付きADDRESSES/proposed候補を保存し、独立読取照合した。新しい会話で保存IDを与えず、期待するIdea/最新概要/Claim/Evidenceと関係状態を取得して再利用できた。新規Claimの共有指定はPR #252/main `e59dff43c93f`へ配送済み。Idea自体はdraftのままであり、5会話・訂正・最終再起動・全main配送を達成したとは扱わない。

#### RP-04D3 根拠と現行関係の契約

- Ideaに接続する正式な意味関係には、`based_on_brief_id`と`based_on_brief_section_index`を対で保存する。章番号は0〜7。既存記録の読み取りには省略を許すが、新規の正式作成は最新の調査済み概要を要求する。
- memory保存の根拠照合は内部組立時に渡した不変概要の取得口で行い、呼出引数で差し替えない。取得口が無い場合は根拠付き関係を拒否する。Neo4jは保存処理内で同じownerの概要を直接照合する。
- 調査済み概要の保存時は最新版と保存時の現行許諾を照合する。受理済み概要から関係を保存するときは、最新版・章・根拠の整合と、登録済みRunの実行時点で有効だった不変許諾履歴を照合する。後日の期限切れ・取消を過去の調査へ遡及適用せず、現在時刻の概要保存validatorを関係保存時に再実行しない。証明できる履歴がない場合は拒否し、現在状態から推測しない。Neo4jのIdea root、関連Campaignのロックは同時更新に対する整合性保持に使い、関係保存に新たな現行調査許諾を要求する意味ではない。memoryは束縛したlatest取得口と保存ロック内の登録済みRun・不変履歴を確認する。
- 指定した章は空欄ではなく、関係のEvidenceを章の`evidence_ids`に含む。本文だけで根拠が存在すると推測しない。概要のownerとIdeaの版が関係の端点に一致することを確認する。
- 過去の根拠を読めるよう、概要の不変な版をID指定で取得する。最新版だけを根拠に読み替える案を却下する。
- ChatGPT向け概要取得は、概要IDと各章の番号・本文に加え、既存の共有可能判定を通過したEvidence IDだけを返す。非共有・欠落した根拠ID、Runの入力・結果、owner判断は返さない。取得した公開項目だけで根拠付き関係の要求を組み立てられることを検査する。
- 訂正時は旧関係を削除せず、新しい関係から`supersedes_id`で明示する。同じ端点・述語なら同じfamilyの次版、端点が変わるなら新familyの初版とする。交差ownerと複数後継への分岐は拒否する。
- 現行検索・経路・有効判定は後継がある関係を除外する。旧関係のID指定参照は残す。後継が撤回された場合に旧関係を自動復活させる案を却下する。
- 関係を追跡・訂正できるよう、共有可能な現行の正式関係pathには実RelationAssertionのcanonical IDを返す。内部pathにIDがあってもMCP投影で落とす現状は別会話試験で確認した不足である。IDがない従来pathは捏造せず省略し、非公開/別owner/旧関係の返却拒否と本文非漏洩を維持する。根拠付き再利用の成功とは分けて、正確なID・端点・Evidenceと拒否例を回帰検査する。実装計画: `founder-graph-mcp-relation-identity.md`。

追加受入条件: Given: 同じIdeaに対する対象T1との関係と根拠付き概要がある。When: 改訂した概要に基づき対象T2へ訂正し、同じ要求を再送する。Then: T1との旧関係は履歴参照できるが現行検索に出ず、T2との関係だけが残り、作成数は再送で増えない。欠落した章・根拠・他ownerの参照は保存前に拒否する。

| ID | 依存 | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- | --- |
| RP-04D3a | 読み取りスパイク | 関係の概要版/章フィールドと概要の不変版取得 | 検査: 対の欠落・範囲外・bool拒否、旧decode維持、owner別のID取得 | 類推可能 |
| RP-04D3b | RP-04D2c,RP-04D3a | 根拠検査と訂正の原子的保存 | 検査: 章/根拠/Idea一致、端点訂正、競合分岐拒否、再送重複0 | 類推可能 |
| RP-04D3c | RP-04D3b | memory/Neo4jの現行検索から旧関係を除外 | 検査: seed/経路/有効判定の旧関係0、ID指定履歴参照成功、後継撤回で旧関係自動復活0 | 類推可能 |

2026-09-26追加検査: Runの終端結果は、開始が承認時刻以降、終了が開始以降・現在時刻以前・許諾期限以内であることを保存前に検証する。承認より前の調査を後から許諾済みとして記録することを拒否する。Idea改訂後に旧Ideaの概要を現行カードへ重ねて表示しない。

PC監査の追補: 既定テストから専用mobileファイルは既に除外済みだが、混在する旧UI検査にも390pxの監査が残っている。`RP-UI-PC`（既知、検査: UI監査は1280×720に固定、旧mobile専用ケースを実行せず、PCの機能・安全・操作検査を保持）で整理する。スマホChatGPTの接続・書込確認はUI監査と別であり、除外しない。

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| Q-RP-01 | スマホ拒否の正確な結果と端末の確認操作が必要になるか | 実装者がtraceを先に調査。本人提供の会話「登録できます」は読取済み | RP-SP-01で不足時にだけ質問 |
| Q-RP-02 | caller認証の追加、公開範囲の変更、追加費用が必要か | 利用者。現在は安全境界を変える許可なし | 必要性を証拠付きで示してから判断依頼 |

現在、新規の製品判断は要求しない。未知の調査結論が新scope/権限/費用を必要とするときだけ判断を求める。2026-09-26再開時の未解決ceo-decisionは4件（#179/#160/#31/#25）で、10件停止条件には達していない。これら旧領域の判断を本MVPの自動承認とは扱わない。

### スコープ外

- スマホ用Dots管理画面の開発・スマホUI監査。スマホChatGPTのread/write確認は別の接続検査として含める。
- ChatGPTの安全保護や確認の無効化、書込みtoolのread-only偽装、拒否された個人情報の無断再送。
- 読み取った自己紹介・家族・住所・保有資産のGit/fixture転載。
- 人的ネットワーク登録画面、自動名寄せ確定、複数利用者、一般公開、PC停止中の利用。
- 旧検索方式の後方互換、理由のない速度比較、完了済み20問benchmarkの再実行。
- 再開指示前のコード修正、DB書込み、サービス再起動、権限変更、PR作成/merge。

### ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| 意味グラフ | ChatGPTが内容を抽出し、Dotsが根拠付き候補を検査・永続化し、次の会話で再利用する | embeddingの近さや履歴構造だけを意味関係と呼ぶ案は創業の再利用価値を実証しない | US-RP-04/05を中心DoDにする |
| グラフ画面 | semantic entity/edgeを主役にし、履歴は内部保持する | DB全ノードの通常表示は版構造と事業内容を混同させる | US-RP-06 |
| 書込み拒否 | 拒否元を調査し、真の副作用に一致するmetadataとserver認可を使う | 全ツールの非破壊指定や安全確認の回避は実際の副作用を隠す | RP-SP-01→RP-01 |
| 本人限定 | OpenAI権限と秘密保管とloopbackを監査し、信頼境界を説明する | owner_id固定だけで本人認証済みとする案は他callerも同じownerとして扱う | US-RP-02 |
| 実装待機 | 読み取り診断と文書改訂のみ実施する | 小さな修正だから先に反映する案は「着手は待って」に反する | 全RP実装は未着手 |

## ゴールモード開始指示

利用者が次の文を送った場合、root coordinatorは`create_goal`で本計画の完遂をobjectiveに設定し、token budgetは指定しない。

```text
Dotsの実装全体計画（docs/plans/dots-implementation-master-plan.md）を完遂するまでゴールモードで自走してください。
実行モデルはsubagent worker/reviewerで gpt-6-luna、reasoning effort medium を使用してください。製品runtimeの検索embedding/rerankは固定revisionのローカル多言語モデルを使用してください。
同時実行枠が4の場合はroot coordinator 1、worker最大3で進め、依存がなく変更ファイルが重ならないready taskを常に優先してください。
root coordinatorは計画、依存関係、変更所有権、受け入れ条件、レビュー、CI、PR、main統合、ユーザー判断境界を管理し、実装と調査はbounded workerへ委譲してください。
会話履歴を正本にせず、本計画、Founder Graphデータモデル正本、GitHub Issue、PR、execution ledgerを正本にしてください。
未決の利用者判断、実外部接続、実データ送信、秘密情報、支出、破壊的移行の境界では対象scopeだけを停止し、他のready taskを続行してください。
各意味単位が完了したらfinish-and-mergeに従い、検査、commit、push、PR、CI、main merge、main smokeまで閉じてください。
全Definition of Doneを満たした場合だけgoalをcompleteにしてください。
```

利用者は後続指示でsubagentの実行モデルを`gpt-6-luna / medium`へ更新した。1M contextの利用可否を完了条件に含めず、全task packetを短い独立文書として渡す。root coordinatorはその時点で利用者が指定する実行環境に従う。

## Luna実行プロファイル

本計画のgoalがactiveな期間は、利用者の明示指定として次を適用する。

| 役割 | model | reasoning | 責務 |
| --- | --- | --- | --- |
| root coordinator | 利用者が現在指定するモデル | 利用者指定 | goal、DAG、WIP、所有権、review、integration、判断境界 |
| implementation worker | `gpt-6-luna` | `medium` | 一つのtask packetの実装、検査、セルフレビュー |
| research / audit worker | `gpt-6-luna` | `medium` | 一つのspike、仕様監査、証跡収集 |
| independent reviewer | `gpt-6-luna` | `medium` | PR差分と受け入れ条件の独立照合 |

Sol、Terra、別providerへのfallbackは行わない。Lunaが利用不能な場合は`model_unavailable`として新規実装を停止し、完了済み成果物のローカル検査と状態記録だけを行う。

Dots製品runtimeのLuna論理キーと、Codex subagentの`gpt-6-luna / medium`指定は別設定として管理する。Dotsの検索embedding/rerankはさらに別のローカルモデルであり、Codex agent用モデルとも混同しない。

## coordinatorの最小context運用

root coordinatorは次だけを常時保持する。

1. active goalと残Definition of Done。
2. phase DAGとready / running / review / blocked / mergedのtask状態。
3. ファイル所有権とWIP。
4. mainの12文字short SHA、open PR、CI状態。
5. 未決decision IDと停止scope。

コード本文の探索、実装、長いtest logの解析はworkerへ渡す。coordinatorはworkerの報告を次の固定形式で受け取る。

```text
TASK: <ID>
RESULT: DONE | CHANGES_REQUIRED | BLOCKED
HEAD: <12-char SHA or none>
FILES: <changed files>
AC: <acceptance criteria result>
TESTS: <command and result>
RISKS: <remaining risk or none>
DECISION: <decision ID or none>
NEXT: <ready dependent task IDs>
```

長いtool outputをhandoffへ貼らず、artifact path、PR URL、失敗行、再現commandを記録する。

### 利用者向け報告

coordinatorは、workerから受け取った内部用の名前や検査結果をそのまま利用者へ転送しない。利用者へは、何が使えるようになったか、どの危険が残るか、元に戻せるか、判断が必要かを日常語で報告する。正確な内部名称は、作業証跡が必要な場合だけ、日常語の説明の後に参考情報として付ける。

## task packet契約

workerへ渡す全task packetは次を含む。

- Task IDと一文objective。
- 先行taskと入力artifact。
- 読む正本file。
- 書込許可fileの列挙。
- 書込禁止file。
- Given / When / Then。
- 実行必須test command。
- 停止条件。
- PR titleとrollback方針。
- model=`gpt-6-luna`、thinking=`medium`。

書込許可fileが重なるtaskを同時実行しない。`App.jsx`とshared styleは同一workerが同時変更せず、integration taskが順番を決める。

## 並列実行規則

同時実行枠が4の場合、root coordinatorを一枠残し、最大三workerを起動する。

taskを並列化できる条件は次の全てである。

- 全dependencyがmergedまたはread-only artifactとして確定している。
- 書込許可fileが他のrunning taskと重ならない。
- 同じschema、API、UI contractの決定を別workerが同時変更しない。
- task単独で検査できる。
- user decision待ちscopeではない。

ready taskが一件の場合は一workerだけを使う。依存を無視して三workerを埋めることは禁止する。

## 状態管理

- 製品要件: `founder-graph-pivot.md`。
- schema: `founder-graph-data-model.md`。
- 実行DAGとDoD: 本書。
- turn横断状態: `docs/operations/dots-execution-ledger.md`。
- 作業割当と判断: GitHub Issue。
- 実装差分とreview: PR。
- 完了済み正本: main。

execution ledgerはtask ID、status、owner task、branch、PR、head SHA、test、blocked decision、updated_atだけを持つ。会話要約を進捗正本にしない。

## 現在地

### 2026-09-26の現在値

- Windows再起動後、通常Neo4j、Dots.の画面、API、通常ChatGPT接続は稼働。ChatGPTの新しい会話から再起動前に保存したIdeaを同一IDで検索した。利用者の明示許可後、通常接続へ識別可能な試験Ideaを1件保存し、同一IDをfetchと検索で再取得した。試験記録は利用者の後日の削除に備えて保持する。
- 合成DBは通常DBの認証交換後に同じ認証ファイルを参照していたため認証失敗になったが、旧container・volumeを保持したまま、別の鍵とvolumeで再構築した。合成MCPで架空Ideaを保存し、別のChatGPT会話から同一IDを再検索した。通常利用には影響しない。合成用ログオンtaskはDisabledのままで、自動起動対象は通常利用のみ。
- 通常DBのneo4j/system両dump、件数と代表読取のmanifest、隔離volumeでの復元・照合は合格。現行の通常接続は外部添付保存部品を使用していない。
- 8観点の不変版・根拠・公開範囲の領域契約、schema v6、Neo4j追加保存、MCP改訂・共有可能な最新版読取、ホーム用の最新版投影と画面部品を実装済み。通常DBの試験IdeaをChatGPTから第3版へ改訂し、別会話で最新版を再取得、PC実画面でも表示した。抽象→具体の意味分類は保存・読取・画面接続を実装し、合成fixtureで検査済み。通常DBにはまだ分類が無く、実データによる段階探索は未検証。
- 通常検索は固定版の多言語E5-base/768次元とmMARCO再順位付けへ切替済み。通常DBの対象13件を補完し、索引ONLINE、代表3問の検索、非公開資料の遮断を確認した。速度比較は再実施しない。中継再起動直後の初回検索は504となり、直後の再試行は成功するため、初回接続の切り分けが残る。
- 作業場所には多数の未コミット変更があるため、一括stage・main切替・PR作成は対象差分の分離まで保留する。直近の工程は上記リンクのMC-01〜11で管理する。

以下の「完了済み」「未完了」は実装時点の履歴を含み、現状との齟齬がある場合はこの現在値を優先する。

### 完了済み

- Founder Graph domain contract、in-memory read/write、Neo4j adapter、MCP read/write、stdio transport。
- Source、Campaign、Run、ReportVersion、Evidence、Claimの基礎validator。
- contact CSV normalizer、instruction scanner、Luna論理model catalog、enrichment proposal contract。
- safe export、report diff、campaign compare、Graph read-only UI。
- Docker Compose、schema migration、manifest、backup / restore helperのnetwork-free検査。
- schema v1→v2の合成変換preview（書込み前の不足・重複・孤立関係検査）。
- Windows Docker Desktop Engine応答。
- schema v2 domain contract、owner境界、RelationAssertionのallowlist。
- schema v2のNeo4j制約・索引migration、同じ移行の再実行、非破壊rollbackの実機確認。
- schema v2のEntityRevision、RelationAssertion、ContentChunk、Facetについて、一時保存とNeo4j向け保存・安全な検索結果の合成parity検査。
- Founder Graphのmax 2-hop read traversal、path、Evidence safe projection。
- 合成MCPの同一接続保存、検索、詳細取得と外部投影からの会話原文除外。
- 合成名刺CSVの全行検査後のPerson / Organization保存、private field境界、再実行時の重複防止。
- 合成人物だけを使うローカル名寄せ候補と上位3件評価。候補は保存処理を持たず、自動統合0件を確認。
- Windows Docker Desktop上の合成Idea保存、停止・再起動検索、Neo4j/system dump、隔離volume load、復元後query。
- 合成Neo4jへ多言語E5の検索索引を適用し、既存17検索対象へembeddingを補完。日本語queryで英語の合成Ideaを先頭に返す交差言語smokeを確認。初回約11.4秒、warm query約0.46秒は単発観測であり、品質評価完了ではない。
- Sentence Transformersの固定済み多言語E5とmMARCO CrossEncoderをoffline/local-onlyで実ロードし、日本語queryに対し英語のFounder Graph候補が日本語候補と無関係なhard negativeを上回る3件smokeを確認。E5初回load+encode約13.7秒、reranker初回load+score約4.5秒の単発観測であり、20問の品質評価やp95の証拠ではない。
- 起動監査で、Docker Desktop自体はWindowsログイン時に起動するが、Neo4j / Dots API・MCP / Secure MCP Tunnelは端末操作なしの自動起動が未構成と判明。Neo4j認証ファイルには別グループの変更権限が継承されていた。内容は読んでいないが、漏えいした可能性があるものとして所有者限定ACLへの修正と資格情報のローテーションを自動起動前に行う。
- 追加質問を「新しい調査」「レポート再編集」「通信再試行」に明示分類するローカル契約。保存や外部送信は開始しない。
- Graph画面用の明示接続部品。読み込み、空、停止、失敗、再試行、結果表示を既存の安全な読み取り口で検査。
- Appから明示クライアントを渡した場合だけGraph画面をlive readへ切り替える接続点。
- finish-and-merge Skill、main保護、CI必須、Auto-merge。

### 未完了

実再起動の更新（2026-09-25）: Windows再ログインで通常Neo4jは自動起動し健康になったが、ChatGPT接続のログオン処理は約19秒早くDBを確認して終了した。タスクの終了結果0だけでは接続成功を意味しない。DB準備後に接続タスクを手動起動するとトンネルが正常になり、ChatGPTの新しい会話で再起動前のIdea題名を取得した。起動順の修正はコードとfocused testまでで、次のWindows実再起動による完全自動復旧は未検証。利用者の新要望である窓なし背景起動・`localhost`操作盤・画面からの停止/再開は別計画（未配送資料: `founder-graph-local-control-dashboard.md`）で受け入れ条件を固定した。以下の旧記述は各時点の履歴であり、この更新を現在値として優先する。

2026-09-25の通常利用接続の更新: 通常DBの認証情報交換・安全な起動設定・ChatGPTへの独立登録は完了した。Windowsログオン用のDB確認タスクと接続タスクは登録・手動起動済みで、通常Dotsへの明示保存と、保存指示のない自然会話からのIdea保存をそれぞれ別会話で再検索できた。架空試験用と通常用が同名だったためにプラグインが架空側へ誤接続したが、表示名を区別してChatGPTの接続一覧を更新後、通常用トンネルへの受信を確認した。実Windows再起動・再ログイン後の自動復旧は未検証。以下の箇条書きには、それぞれの工程を実施した時点の履歴も含むため、通常接続の現在値はこの更新を優先する。

- schema v2のdomain contract、migration、保存・読取parityは実装済み。既存v1 data変換は未完了。MCPはIdeaとSourceRevision/ContentChunk構造、Asset、Evidence、および根拠付きRelationAssertionの保存に対応し、同一要求の再送と関係訂正の履歴も検査済み。物理schema v5の制約は、既存の必須項目欠落や重複があれば変更前に停止する。通常利用DBへのschema v5適用は完了したが、通常Dots API/MCP serviceの起動・再起動確認は未完了。
- UbuntuからDocker Desktopへの接続は、WSL経由でDocker Engine 29.8.0とCompose 5.5.1の応答まで確認済み。Founder Graph用Composeのhealth確認とmanifest一致は未完了。
- Compose live volumeのmanifest一致、Attachmentとmanifestの同generation restore。
- 通常利用Neo4jのschema v1→v5適用は2026-09-25に完了（18 migration queries）。Idea 3件とFounderGraphAudit 3件の件数は変わらず、グラフ本文・関係は変更していない。v5一意制約、CJK full-text、vector indexはONLINE。通常Dots API/MCP serviceと通常利用live volumeのWindowsログイン後自動起動は未構成。Composeの`restart: unless-stopped`はDocker Engine起動後のコンテナ再開だけを扱い、利用者が明示停止した場合は再開しない。認証ファイルの安全な受渡しと資格情報ローテーションを完了してから、通常利用経路の自動起動を構成する。P5-04はChatGPT接続を検証する合成専用volumeだけの起動経路であり、このgateを代替しない。
- FastAPI / stdioの既定runtime選択とNeo4j障害時のfail-closedは実装済み。Composeで選んだNeo4jの停止・再起動後に通常runtimeから確認するgateは未完了。
- ChatGPT Secure MCP Tunnelの登録は合成DB限定で利用者が許可済み。2026-09-25、通常Chatの一回の発話でIdea / Person / Claim / Idea→Claim（ADDRESSES）/ Evidence / Person→Idea（期限付きRelationAssertion）を順に保存し、返却IDだけを引き継いで検索・Evidence取得まで完了。別の自然会話では既存の地域工房案を探し、新しい小売実験Ideaと架空Person「青海はるか」、期限付きCAN_CONTRIBUTE_TO関係を保存したことをMCP検索で確認。検索で関係種別・状態・確信度・期限が一致し、連絡先・非公開メモは返らなかった。前者のEvidence詳細は評価metadataだけで、source/chunk固有のフィールドは返っていない。一方、shareable Ideaの要約・snippetは検索結果へ返る仕様どおり表示された。合成Neo4jの永続volume再起動後に既存pathをMCPから再検索できたが、その再起動後にChatGPT UIから再実行したわけではない。代表会話5件とWindows実再起動後の確認は未完了。
- Graph RAGの固定20問品質試験では、現行small+WRRF構成がRecall@20 .783 / HitRate@5 .55、E5-base+multilingual mMARCO reranker候補が.95 / 1.00で合成fixtureの順位品質gateを通過し、全候補でpath/evidence coverage 100%、安全違反0件だった。高品質候補は合成ChatGPT接続の検索経路へ可逆に適用済みで、英語の言い換えから日本語の架空Ideaを検索・取得できた。通常runtimeと通常DBの既定検索構成には未適用。再順位付けで処理時間は増えるため、モデルや検索経路の変更等の理由がない限り性能比較を繰り返さない。
- 合成専用のログオンtaskとTunnel起動確認は登録済み。Tunnel中のWSL維持とログオフ用taskの手動実行でTunnel・待機task・Ubuntuが停止することを確認済み。synthetic DB再起動後のMCP検索とTunnel doctorも成功。2026-09-25にバッテリー駆動でtaskがQueuedとなりTunnelが停止する欠陥を発見し、登録scriptと既存taskの電源条件を修正。バッテリー駆動中にtask Running / Tunnel active / health ok / MCP再検索を確認した。ただしバッテリー中の長時間維持、Windows実ログオフ通知、Windows全体の再起動・再ログイン、再起動後にChatGPT UIから同じ保存済みIdeaを検索する試験は未完了であり、P5-04を完了にしない。
- 通常利用DotsをChatGPTへ接続する前の安全gateでは、Personの連絡先・非公開メモに加え、SourceRevision / ContentChunkの本文・詳細を共有設定の誤操作時にもMCPから返せないよう型で拒否し、検索・詳細取得の双方で検査する。通常DBの旧認証情報を交換し、本人限定の認証ファイル・live専用volume照合・独立Tunnel起動を確認するまで、実データ接続は開始しない。
- Graph全体検索からResearchBriefを作り、許諾後にDeep Researchへ渡す実経路。
- Deep Research完了後のRun、Evidence、ReportVersion write-back。
- Graph UIの実backend接続、訂正、削除impact、実file export。
- 外部AIを使う名寄せ順位付け評価と、本人確定後だけ実行できる統合処理。
- private full archive、soft delete propagation、safe export。
- 実データ投入前security reviewと既存データ移行判断。

## phase DAG

```text
P0 Control Plane
  -> P1 Schema v2
      -> P2 Neo4j Real Runtime
          -> P3 Local Capture/Search
              -> P4 Assets/People
              -> P5 ChatGPT Synthetic Connection
                  -> P6 Research/Report Write-back
          -> P7 Live UI
      -> P8 Backup/Delete/Export
P3 + P4 + P5 + P6 + P7 + P8
  -> P9 Real-data Readiness and Legacy Disposition
      -> COMPLETE
```

P4とP7はP3完了後に並列実行できる。P5はP3と外部接続decision後に開始する。P8はP2完了後に開始できる。P9は全gate完了後に開始する。

## ユーザーストーリーと受け入れ条件

### US-MP-01 会話から永続保存する

As a 単独利用者, I want ChatGPTで話したアイデアをDotsへ保存したい, so that 再起動後も再利用できる。

Given: schema v2のNeo4j、MCP write、合成会話が起動している

When: capture_ideaを実行し、DotsとNeo4jを停止して同じvolumeで再起動する

Then: 同じIdea anchor、SourceRevision、EntityRevision、provenanceをsearchとfetchで取得できる。

### US-MP-02 資産と人脈を照合する

As a 単独利用者, I want 新しいIdeaを知識、経験、人物、組織へ照合したい, so that 誰と何を検証するか決められる。

Given: Asset、Person、Organization、RelationAssertionが保存されている

When: IdeaについてGraph RAG検索する

Then: 上位結果は根拠path、confidence、status、有効期限を持ち、proposed関係をconfirmedとして表示しない。

### US-MP-03 許諾後に複数調査する

As a 単独利用者, I want 調査目的を一度許諾して複数回試したい, so that 結論を比較できる。

Given: 目的、範囲、外部送信field、試行予算を確定したCampaignがある

When: ChatGPTが二つのResearchRunを実行してwrite-backする

Then: Run、input snapshot、Evidence、ReportVersionは別IDで保存され、旧版を変更せず比較できる。

### US-MP-04 訂正と削除を追跡する

As a 単独利用者, I want 誤りを訂正し不要な情報を削除したい, so that 現在の検索と過去判断を区別できる。

Given: Sourceを参照するClaimとReportVersionがある

When: Sourceをsoft deleteする

Then: 現在検索から除外され、過去ReportVersionにはunavailable、hash、削除時刻が表示される。

### US-MP-05 Lunaで再現可能に実装する

As a 製品責任者, I want Luna workerだけで計画を進行したい, so that 高価な基幹agentへ依存せず反復できる。

Given: 一つのtask packetがreadyである

When: Luna workerが実装、test、セルフレビューを完了する

Then: task packetの全AC、test、file ownership、handoff fieldが満たされ、coordinatorが元コード全文を読み直さずreview判断できる。

### US-MP-06 合成接続で検証済みの検索構成を使う

As a 単独利用者, I want 日本語の会話から日英の過去アイデアと人物を根拠付きで探したい, so that 新しいアイデアを既存の資産と結び付けられる。

Given: 合成専用Neo4jと固定済みの多言語E5-base / mMARCOモデルがあり、通常用384次元indexが保持されている

When: 合成専用の検索構成を明示して起動し、Dots検索サービスと合成Neo4jを同じvolumeで再起動する

Then: 768次元indexがONLINEでE5-base / mMARCO候補40件の構成が選ばれ、同じIdea・根拠付き関係をMCPから検索できる。通常利用のモデル、384次元index、reranker OFF設定は変わらない。

### US-MP-07 自然な会話から蓄積する

As a 単独利用者, I want 保存命令を言わずに創業アイデアを話したい, so that 後の会話で過去の発想や人脈を自然に再利用できる。

Given: 合成専用Dots接続を対象メッセージで選んだChatGPT会話と、合成Neo4jが利用可能である。MVPではメッセージごとの選択を利用者が許容している

When: 「保存」「Dotsへ書く」などを含まない日常的なアイデア発言をし、別の新規会話でその話題を尋ねる

Then: 最初の会話中にDotsへの書込みが生じ、別会話から同じIdeaを検索・取得できる。単なる雑談では書込みがなく、フル調査は利用者の許諾なしに始まらない。接続の選択が必要な場合は操作条件として明示し、未選択の通常会話でも動くと主張しない。

## 実装task

### P0 Control Plane

| ID | Dependency | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- | --- |
| P0-01 | なし | 本計画とdata modelをAGENTS / HANDOFFから正本化 | 検査: 正本link、model override、finish-and-merge routeが各一件存在する | 既知 |
| P0-02 | P0-01 | execution ledgerとtask packet template | 検査: task、PR、SHA、test、decisionを一行で追跡できる | 既知 |
| P0-03 | P0-01 | Founder Graph用GitHub IssueをDAG taskへ整合 | 検査: pre-pivot Issueをcurrent taskへ誤割当せず、ready taskにownerとdependencyがある | 類推可能 |

### P1 Schema v2

| ID | Dependency | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- | --- |
| P1-SP-01 | Q-DM-01 | schema v1→v2 fixture変換spike | 検査: 欠落field、重複anchor、孤立edge、rollback結果を出力する | 未知 |
| P1-01 | P1-SP-01 | stable anchor / EntityRevision domain contract | 検査: anchor ID維持、current pointer一意、revision不変testが成功する | 類推可能 |
| P1-02 | P1-SP-01 | RelationAssertion / Facet / ContentChunk contract | 検査: predicate、根拠、期限、chunk locatorのallowlist testが成功する | 類推可能 |
| P1-03 | P1-01,P1-02 | Neo4j migration v2とrollback | 検査: 実Neo4jの空DBとv1 fixtureの双方でmigration / rollbackが成功する | 類推可能 |
| P1-04 | P1-03 | v2 read/write parity | 検査: in-memoryとNeo4jで同じmanifestと代表query結果になる。合成v2全node typeのfetch/search parityを実装・検査済み | 類推可能 |

### P2 Neo4j Real Runtime

| ID | Dependency | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- | --- |
| P2-SP-01 | P1-03 | Ubuntu→Docker Desktop接続spike | 検査: Ubuntuでclient/server versionとCompose healthを取得する | 未知 |
| P2-01 | P2-SP-01 | secret、volume、health、shutdownを持つlocal runtime | 検査: secretがGit/logへ残らずNeo4j healthがhealthyになる | 類推可能 |
| P2-02 | P1-04,P2-01 | schema migrationとfixture load | 検査: schema version、constraint、node/assertion countがmanifestと一致する | 類推可能 |
| P2-03 | P2-02 | restart persistence gate | 検査: 停止前後のmanifest、代表10問、revision pointer hashが一致する | 類推可能 |
| P2-04 | P2-03 | local composition既定をNeo4jへ切替 | 検査: 起動時Neo4j、停止時503、公開fallbackなし、rollback flagが成功する | 類推可能 |
| P2-05 | P2-04 | Windowsログイン後のDocker / Neo4j自動起動とhealth待機 | 検査: 認証情報交換後、サインイン時に端末操作なしで同じlive volumeのNeo4jがhealthyとなる。未ログイン・明示停止中は非公開のまま。秘密値がGit・平文ログへ出ない。認証情報交換・実DB照合・本人のログオン用タスク登録・手動起動での正常終了は完了。Windows実再起動後の自動起動と健康確認は未完了 | 実再起動試験待ち |

### P3 Local Capture / Search

| ID | Dependency | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- | --- |
| P3-01 | P2-04 | capture_ideaのSource→Idea transaction | 検査: 冪等再送でanchor一件、Source原文一件、revision一件になる | 類推可能 |
| P3-SP-04 | P2-04 | Neo4j 5.26 full-text Japanese analyzer確認 | 検査: 利用可能analyzerと同一条件20問の比較で`cjk`を選定。v4 migration後、合成専用Neo4jのfull-text/vector両indexがONLINEであることを実機確認。通常DBへのmigrationは別gate | 検証済（合成専用instance） |
| P3-02 | P2-04,P3-SP-04,P4-06 | Neo4j full-text + multilingual-e5-small vector + WRRF + bounded 2-hop Graph RAG候補取得 | 検査: 100件以上の合成検索対象と、日英・交差言語を含む固定20問でRecall@20 0.90以上、HitRate@5 0.80以上、直接候補を含む必須path/evidence coverage各100%、owner越境・誤った根拠pathが0件 | 未知 |
| P3-SP-06 | P3-02 | 検索pathの方向・関係条件、MCP検証、reranker既定値を是正 | 検査: 逆向き探索でも元edgeのsource/predicate/targetと探索方向を区別し、owner/current/expiry条件と実在edgeを検証する。rerankerは既定OFFで、明示設定後にのみ動き、期限超過時は成功応答にしない | 類推可能 |
| P3-SP-05 | P3-02,P3-SP-06 | 固定20問・100件以上の合成corpus、scorer、MCP実検索benchmark | 検査: Neo4j上でWRRF基準順位と実reranker順位を別々に取得し、Recall@10/20/50、HitRate@5、nDCG@10、MRR@10、全問path/evidence coverage、8種の安全違反、query別cold/warm latencyを記録する。schema v4の同じ123件/40関係/20問でreranker候補上限40/20/10を比較。40件: R@20 .77、Hit@5 .95、nDCG .705、MRR .95、warm p95 7.795秒。20件: R@20 .58、Hit@5 .85、nDCG .587、MRR .85、R@10 .51、R@50 .85維持、path/evidence 90%、warm p95 4.393秒、初回11.418秒、peak RSS 1,953,132 KiB。10件: R@20 .58、Hit@5 .65、nDCG .455、MRR .65、R@50 .85維持、path/evidence 90%、warm p95 2.578秒、初回8.031秒、peak RSS 1,921,064 KiB。全条件で安全違反0。上限20を明示opt-in時の候補数として採用したが、rerankerはOFFのまま。WRRF基準R@20 .58（目標.90）、Hit@5 .55（目標.80）、path/evidence 90%（各100%目標）のため、Graph RAG全体は未達。速度値は各質問1回だけの探索測定であり、標準偏差がないため暫定値。 | 未知 |
| P3-SP-07 | P3-SP-05 | 検索速度の一回限りの反復・paired基準比較 | 検査: 同一の一時Neo4j instanceでbaseline/cap20/cap40を同じ固定20問ごと5回warm測定する。実測は各条件100標本。固定seedで質問・roundごとに条件順を入れ替え、mean/sample SD/median/p95/max、質問別統計、同一質問・roundでのpaired差、Linux/WSL load averageを出力する。実測値はローカルGraph RAG計画へ記録済み。Embedding/reranker変更、検索経路の実質変更、データ量の大幅増、性能劣化の診断、利用者の明示依頼がない限り再測定しない。 | 検証済（2026-09-25、合成専用instance） |
| P3-SP-03 | P3-02,P3-SP-05,P3-SP-06 | local cross-encoder reranker評価 | 検査: 実際のWRRF候補を使い順位品質、Recall@50、cold/warm latency、memoryを実測する。上限20ではnDCG .416→.587、Hit@5 .55→.85、MRR .538→.85、Recall@50 .85維持。初回11.418秒、warm p95 4.393秒は旧・各問1回の探索値であり、標準偏差を含まない。反復100標本ではwarm mean 3.493秒、sample SD 0.679秒、p95 4.756秒。上限40も旧1回値のp95 7.795秒に対し、反復100標本でmean 6.342秒、sample SD 1.138秒、p95 7.825秒。上限10のnDCG .455 / Hit@5 .65とp95 2.578秒は一回のみの探索値。process peak RSSは1,953,132 KiBだが、rerankerを含むプロセス全体値であり、baselineとの差分memoryは未計測。WRRF recall/path品質gateも未達のため、rerankerは明示opt-inのまま。現行opt-in候補数は20 | 未知 |
| P3-03 | P3-SP-03 | search / fetch MCPのsafe projection | 検査: local_only field 0件、pathとEvidence ID欠落0件になる | 類推可能 |
| P3-04 | P3-01 | SourceRevisionの決定的ContentChunk生成とcapture receiptの参照ID | 検査: 根拠付き関係保存計画のGR-WR-01を満たし、本文なしの同じIDを再送時にも返す | 類推可能 |
| P3-05 | P3-04 | Source / SourceRevision / ContentChunkのschema v2構造edge保存と既存graphの整合性検査・冪等補修 | 検査: in-memoryとNeo4jのHAS_SOURCE_REVISION、CURRENT_SOURCE_REVISION、HAS_CHUNKの向き・端点・重複数が一致し、owner / revision / current pointer / chunk ordinalの不整合は書込み前に停止する。既存データを事前検査後に補修し、再実行でedgeや監査が増えない。実装、fake Neo4j parity、専用loopback disposable Neo4jでのpreview無変更・不足edge apply・再実行no-opを確認。CLI applyは専用loopback instance・合成ownerの明示時だけ許可。既存ChatGPT合成graphのread-only previewは安全な認証経路が整うまで保留 | 類推可能 |

| P3-SP-08 | P3-SP-05,P3-SP-06 | q-015/q-016の合成Graph RAG検索経路trace | 検査済: 空のloopback専用Neo4j・canonical合成fixture・既定WRRF/reranker OFFで各1回。完全なpathとEvidenceは生成されたが、Asset最終順位はq-015で57位、q-016で65位。q-015はfull-text対象0、vectorのIdea 39位・Person 50位・Asset圏外。q-016はfull-text対象なし、vectorのPerson 25位・Idea/Asset圏外。速度測定なし。結果はlocal GraphRAG計画に記録 | 検証済 |
| P3-SP-09 | P3-SP-08 | 多言語候補検索のembedding品質改善 | 検証済: 固定20問・eligible合成資料120件を使うdense-only比較。small→baseでR@20 .633→.800、Hit@5 .800→.850、nDCG@10 .548→.620、MRR@10 .657→.750、R@50 .867→.917。ja→en R@20 .333→.400、en→ja .333→.867。q-015 Asset順位55→50、q-016 50→58。安全違反0。path/evidenceと速度は未測定。baseは候補のまま、既定small・schema・保存vector・通常DBは無変更 | 検証済（dense-only、2026-09-25） |
| P3-SP-10 | P3-SP-09,P3-SP-08 | disposable Neo4jでsmall対baseのGraphRAG品質確認 | 検証済: canonical合成graph、schema v5/CJK、small既定384次元indexと別768次元E5-base index、WRRF/graph expansion/reranker OFF、MCP公開入口の固定20問。Recall@20 .667→.800、Hit@5 .550→.600、nDCG .404→.422、MRR .463→.505、Recall@50 .933→.967、path/evidence 90%→95%、安全違反0。q-015/q-016の期待Person/Idea/Assetは全てtop-50へ入りpath/Evidenceも確認。速度・CPU測定なし。品質gate未達のため既定smallと通常DBを維持 | 検証済（品質gate未達） |
| P3-SP-11 | P3-SP-10 | E5-baseと既存mMARCO rerankerのGraphRAG品質確認 | 検証済: 同じ合成fixture/使い捨てNeo4j/ChatGPT向けMCP公開入口でsmall+WRRF、base+WRRF、base+mMARCO CrossEncoder cap20を固定20問比較。R@20 .667/.800/.800、Hit@5 .550/.600/.900、nDCG .404/.422/.659、MRR .463/.505/.850、R@50 .933/.967/.967、path/evidence 90%/95%/95%、safety 0。rerankerは順位品質を改善するがRecall@20と全path/evidence gate未達。速度測定なし。既定設定維持 | 検証済（品質gate未達） |
| P3-SP-12 | P3-SP-11 | E5-base + mMARCO cap40の検索品質確認 | 検証済: 同一MCP公開入口の固定20問。small+WRRF / base+WRRF / base+mMARCO cap20 / cap40のR@20 .667/.800/.800/.917、Hit@5 .550/.600/.900/1.00、nDCG .404/.422/.659/.746、MRR .463/.505/.850/.950、R@50 .933/.967/.967/.967、path/evidence 90%/95%/95%/95%、safety 0。q-015/q-016主要nodeはcap40でtop-7、両方path/Evidenceあり。順位/safety gate通過、path/evidence 100% gate未達。速度測定なし、通常DB不変 | 検証済（総合quality gate未達） |
| P3-SP-13 | P3-SP-12 | 残り1問のpath/evidence未到達原因診断 | 検証済: missing caseはq-011。Idea vector rank27で唯一のWRRF seed、Person/Assetはvector候補外。DBのrelation/Evidenceは存在し、graph expansionが両者へのpathおよび完全Person→Idea→Asset pathを生成した。最終内部順位Person52/Asset51がMCP top50 cutoff外。safe q-011 internal traceとMCP safety 0、通常DB不変。速度未測定 | 検証済 |
| P3-SP-14 | P3-SP-13 | E5-base + mMARCO cap40でのscore decay品質評価 | 検証済: decay .8/.9/1.0の順にRecall@20 .917/.917/.950、Hit@5 1.00/1.00/1.00、nDCG .746/.747/.766、MRR .950/.950/.950、Recall@50 .967/1.00/1.00、path/evidence 95%/95% → 100%/100% → 100%/100%、safety 0。試験時の通常設定は変更せず | VERIFIED |
| P3-SP-15 | P3-SP-14 | 現行通常構成でのscore decay確認と安全な既定更新 | small + WRRF / reranker OFFでdecay .8/.9/1.0のR@20 .667/.700/.783、Hit@5 .550一定、nDCG .404/.428/.451、MRR .463/.463/.456、R@50 .933/.950/1.00、path/evidence 90%/90% → 90%/90% → 100%/100%、safety 0。base + WRRFでも1.0が0.8を上回り、path/evidenceを100%へ改善。同点は直接候補・短いpathを優先。decayのみ1.0へ更新し、model/reranker/schema/index/DB不変。backend 649 passed / 2 skipped、service再起動、Tunnel doctor、synthetic MCP read smokeを確認。総合R@20/Hit@5品質gateは未達、速度未測定 | REVIEW |

| P3-SP-16 | P3-SP-15 | 関係版IDを保ったGraph RAG pathのEvidence集約と決定的選択 | 同じRelationAssertion IDだけEvidenceを統合し、異なるassertion ID・status/confidence/有効期間、legacy RelationとAssertion、反対向きedgeは別pathとして保持。MCP投影は内部assertion IDを返さない。focused 81 passed、backend 651 passed / 2 skipped、py_compile・diff check passed。quality-only 20問: small+WRRF R@20 .783 / Hit@5 .55 / path-evidence 100%; E5-base+WRRF .817/.60/100%; E5-base+mMARCO cap40 .95/1.00/100%、安全違反0。latency未測定、使い捨てNeo4j削除、通常DB・既定index不変 | REVIEW |
| P3-SP-17A | P3-SP-16 | E5-baseの固定revision・local-only読込とモデル記録 | 検証済: E5-baseのrevision、license、重み/tokenizer hash、runtime version、768次元をmanifestに記録し、既存mMARCOも記録。cache欠落時はofflineで停止し、通常E5-small既定は不変。focused 5 tests passed | 検証済（合成用の準備） |
| P3-SP-17B | P3-SP-17A | 合成Neo4jだけへの別768次元indexとembedding補完 | 検証済: 合成専用volume / owner / loopback Boltを照合し、71/71検索対象へ別768次元propertyを補完。768次元と従来384次元のindexは両方ONLINE、再実行no-op、node ID・edgeのfingerprint不変。通常DB無変更。focused 11 tests passed | 検証済（合成DBのみ） |
| P3-SP-17C | P3-SP-17B | 合成MCP検索のE5-base / mMARCO候補40件構成 | 検証済: 合成専用serviceで明示選択し、MCP search/fetchで`hybrid_local_reranked`、日本語Ideaを英語の言い換えから取得。通常runtimeはsmall / 384次元 / reranker OFF。backend 678 passed / 2 skipped。Windows実再起動後の構成・結果確認はP5-03/04に残す。速度比較は追加せず | 検証済（合成service稼働中） |

### P4 Assets / People

| ID | Dependency | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- | --- |
| P4-01 | P3-01 | OwnerProfile、InstructionArtifact、Asset取込 | 検査: hash差分だけが新revisionとなり秘密文字列が保存されない | 類推可能 |
| P4-02 | P3-01 | Person / Organization手入力とCSV取込 | 検査: 合成名刺10件でfield loss 0件、private投影0件になる | 類推可能 |
| P4-SP-03 | P4-02 | Luna名寄せ候補評価 | 検査: top-3再現率0.90以上、誤自動merge 0件を記録する | 未知 |
| P4-03 | P4-SP-03 | merge確認とRelationAssertion UI/API | 検査: 本人確認なしのconfirmed / MERGED_INTOが0件になる | 類推可能 |
| P4-04 | P3-05,P4-02 | SourceRevisionとContentChunkに結び付くEvidenceの用途限定MCP write | 検査: 根拠のowner・型・存在を保存前に確認し、同一内容の再送は重複しない | 類推可能 |
| P4-05 | P4-04 | link_entitiesのschema v2 RelationAssertion保存 | 検査: ASSERTS_FROM / ASSERTS_TO / EVIDENCED_BYと監査を一transactionで保存し、network relationをconfirmedにしない | 類推可能 |
| P4-06 | P4-05 | RelationAssertionを通るGraph search / fetch | 検査: status、confidence、expiry、根拠IDが同じ安全な結果に残り、private fieldが0件になる | 類推可能 |

### P5 ChatGPT Synthetic Connection

| ID | Dependency | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- | --- |
| P5-SP-01 | D-EXT-01,P3-03 | Secure MCP Tunnel tool discovery | 検査: 合成データだけでsearch、fetch、capture_idea、capture_asset、capture_personを含むtool discoveryを記録する | 検証済み（2026-09-25、接続更新後に5 tools確認） |
| P5-01 | P5-SP-01 | 代表会話5件の検知→保存→preflight（自然会話試験（未配送資料: `founder-graph-chatgpt-natural-capture.md`）） | 検査: 保存命令のない発言を含む5件で保存ID、idempotency hash、検索件数、調査未開始を記録し、雑談対照は無書込み。新規会話から再取得する | 類推可能 |
| P5-02 | P5-01 | ChatGPT接続runbookとredacted evidence | 検査: credential、会話原文、個人連絡先がartifactに0件になる | 類推可能 |
| P5-03 | P3-03,P5-SP-01,P2-03,P5-04 | ChatGPT direct Graph RAG synthetic verification | 検査: 合成Idea / Asset / Person / Evidenceを保存・検索・取得する。人物→アイデアの関係は期限と根拠付きで保存し、ChatGPT検索から同じpathとEvidence IDを確認。Evidence取得は評価metadataだけとし、contact/private_notes/source textの露出を0件にする。write toolの共通receipt outputSchemaを通じ、返却target_idを手入力なしに次のtoolへ渡せることを試験する。Neo4j container再起動後に同じnode・pathを再検索し、代表会話5件とWindows再起動・再ログイン後の同一操作も確認する | 進行中（2026-09-25、通常Chatの一回の発話でIdea / Person / Claim / ADDRESSES / Evidence / 期限付きPerson→Idea関係を返却IDで連鎖保存し、検索とEvidence fetchまで実機確認。Evidence詳細のsafe projectionに本文・連絡先・private_notesなし。shareable Ideaの要約/snippetは検索応答へ含まれる。合成DBの永続volume再起動後は保存済みデータをMCP経由で再検索できたが、この再起動後のChatGPT UI再実行は未確認。代表会話5件、Windows実再起動・再ログインも未了） |
| P5-04 | P5-SP-01 | Windowsログイン後の合成DB / WSL / MCP / Tunnel起動とログオフ停止 | 検査: WindowsログオンタスクがDocker Desktop公式CLIを使ってEngineを起動し、合成専用DBが既に稼働・Bolt接続可能な場合だけTunnelサービスを開始する。systemdだけではWSL distroが残らないため、Tunnelがactiveな間だけ低負荷の待機プロセスを保持し、本人のログオフ時はWinlogon event 7002の本人SIDを契機にTunnelサービス停止後、待機タスクも終了する。明示停止DBは起動・再公開せず、待機プロセスも残さない。Windowsの電源接続中・バッテリー駆動中の双方で起動と維持ができる設定とする。Dots runtimeはowner-only ACL等で保護した認証ファイルから`neo4j/<password>`を読み、profile、argv、Git、ログへpassword本文を複製しない。欠落・symlink・不正形式はfail closed。Windowsログオン後2分以内に`wsl --list --running`でUbuntuが稼働し、ChatGPTからsearch / capture / fetch可能。ログオフ後はTunnel停止、秘密値ログ漏えい0件。実際のWindows再起動・再ログイン後も同じ結果を確認する | 一部検証済み（合成DBの永続volume再起動後、保存済みIdeaと根拠付き人物関係をMCP経由で再検索。バッテリー時に既存taskの電源条件を修正しRunning / Tunnel active / health ok / MCP再検索を確認。長時間維持、Windows実ログオフ通知・実再起動・再ログイン後のChatGPT UI確認は未了） |
| P5-LIVE-01 | P2-05,P5-03,P9-SP-LIVE | 通常Dotsの独立したMCP/Tunnel接続（安全な有効化計画（未配送資料: `founder-graph-live-mcp-activation.md`）） | 検査: 認証情報交換とprivate projection review後にだけ有効化し、owner・Bolt URI・container/volume/labels・loopback・健康状態を照合する。通常small/384/reranker OFF、本人限定の認証ファイルを使う。2026-09-25、独立TunnelとChatGPT接続を有効化し、共有可能なIdeaの読み書き、保存命令なしの自然記録、別会話からの再取得を実機確認。Windows再起動後の自動接続と再取得は未完了 | 実再起動試験待ち |

### P6 Research / Report Write-back

| ID | Dependency | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- | --- |
| P6-01 | P5-01 | Dots全体検索→ResearchBrief→許諾preflight | 検査: 目的、範囲、field category、試行予算、期限がsnapshot化される | 類推可能 |
| P6-SP-02 | P6-01 | Deep Research一回とwrite-back spike | 検査: 一Campaign、一Run、一ReportVersion、通知時刻、write receiptを記録する | 未知 |
| P6-02 | P6-SP-02 | 二回調査と追加質問のRun分類 | 検査: 方針変更は新Run、再構成は新ReportVersion、transport retryは同Runになる。接続前の明示分類契約は[`founder-graph-follow-up-classification.md`](founder-graph-follow-up-classification.md)で実装済み | 類推可能 |
| P6-03 | P6-02 | 固定8章生成、差分、訂正 | 検査: 8章、Claim区分、Evidence、撤退line、roadmapが旧版不変で保存される | 類推可能 |

### P7 Live UI

| ID | Dependency | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- | --- |
| P7-01 | P3-03 | Graph UIをlive read APIへ接続 | 検査: empty、loading、unavailable、retry、data表示のcomponent/E2Eが成功する | 類推可能 |
| P7-02 | P4-03 | Person、Asset、RelationAssertion確認UI | 検査: proposed確認、reject、merge preview、keyboard操作が成功する | 類推可能 |
| P7-03 | P6-03 | ReportVersion、Run比較、訂正UI | 検査: 8章差分、根拠、旧版、unavailable参照を表示する | 類推可能 |

### P8 Backup / Delete / Export

| ID | Dependency | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- | --- |
| P8-SP-01 | D-BACKUP-01,P2-03 | 世代付きprivate archive / isolated restore spike | 検査: Neo4j、Attachment、manifestを同generationで復元しhash一致を確認する | 未知 |
| P8-01 | P8-SP-01 | backup / restore commandとUI状態 | 検査: success、partial、failed、保持artifactを表示し元volumeを変更しない | 類推可能 |
| P8-02 | D-DELETE-01,P8-01 | soft delete impact previewとpropagation | 検査: search除外、Report unavailable、export除外、audit保持が一致する | 類推可能 |
| P8-03 | P6-03,P8-01 | safe JSON / Markdown / DOCX / PDF export | 検査: 選択scopeだけを出力しprivate field 0件、8章欠落0件になる | 類推可能 |

### P9 Real-data Readiness / Legacy Disposition

| ID | Dependency | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- | --- |
| P9-SP-LIVE | P3-03,P4-04,P5-03 | 通常Dotsを外部接続する前の限定安全審査 | 検査: Person連絡先・非公開メモ、SourceRevision / ContentChunk本文がshareable設定の誤りでもsearch/fetchに出ない。通常DBの直前復元可能な保全策、資格情報交換と本人限定保管、新旧認証の曖昧な結果からの復旧、live/syntheticの保存先取り違え拒否を実証し、P0/P1未解決0件。全製品完成監査P9-01とは区別する | 一部実装済み（privacy型拒否とfake guardのみ） |
| P9-01 | P3,P4,P5,P6,P7,P8 | security / privacy / recovery review | 検査: threat model、egress、secret、restore、deleteのP0/P1未解決が0件になる。特にChatGPT向けsearch/fetchはSourceRevision / ContentChunkを共有設定に関係なく拒否し、Person連絡先・非公開メモも返さない。通常用認証情報の交換と本人限定の保管、合成・通常volumeの誤接続拒否を接続前に実証する | 類推可能 |
| P9-SP-02 | P9-01 | 既存Postgres / localStorage実inventory | 検査: owner別count、hash、legacy mapping、変換失敗一覧を作る | 未知 |
| P9-02 | D-LEGACY-01,P9-SP-02 | 変換またはread-only archive | 検査: 変換countまたはarchive count、rollback、旧版参照を照合する | 類推可能 |
| P9-03 | D-REAL-01,P9-01,P9-02 | 実データcanary投入 | 検査: 一Idea、一Person、一Sourceで保存、再起動、検索、backupが成功する。削除・復元の試行は許諾済みの隔離コピーだけで確認し、通常の保存データは削除しない | 類推可能 |
| P9-04 | P9-03 | 初期完成監査 | 検査: 本書の全DoD、CI、main smoke、runbook、known limitationを照合する | 既知 |

表の`P3`、`P4`、`P5`、`P6`、`P7`、`P8`は各phase内の全task完了を表す。

## 質問リスト / 利用者判断boundary

| ID | 判断 | 推奨既定 | 停止scope | 期限 |
| --- | --- | --- | --- | --- |
| Q-DM-01 | schema v2を採用するか | MVPの仮データ範囲でstable anchor + immutable revision + RelationAssertionを採用 | none（実データ投入前の安全確認は残す） | 2026-09-23 |
| D-EXT-01 | ChatGPTへSecure MCP Tunnelを初回登録するか | 合成データだけでの登録は利用者承認済み | P5の合成tool discoveryと証跡整理は継続、実データ・外部調査は別gate | P5-SP-01前 |
| D-BACKUP-01 | private archive保護とartifact構成 | アプリ層暗号化、同generationの別artifact | P8-SP-01以降 | P8-SP-01前 |
| D-DELETE-01 | Source delete後の過去Report | Reportを残しunavailable表示 | P8-02以降 | P8-02前 |
| D-LEGACY-01 | 旧データの扱い | 実データが少ない間はJSON export + read-only archive | P9-02だけ | P9-SP-02後 |
| D-REAL-01 | 実会話、名刺、個人資料を初投入するか | 合成gateとsecurity review後に一件canary | P9-03以降 | P9-03前 |

判断待ちは該当scopeだけを止める。別phaseのready taskを停止しない。

## PRとintegration

- 一PRは一taskまたは同じ受け入れ条件を成立させる縦切りtask群に限定する。
- 500行を超える場合、生成物、fixture、schema、adapter、UIを分離できるか先に確認する。
- PR head更新ごとに短い必須CIとreviewを再実行する。画面、Storybook、PDF、DOCXを変更した場合は、節目の全確認を手動で実行する。
- required `quality`成功前にmergeしない。
- merge後はmain smokeとdependent task deliveryを同じturnで閉じる。
- schema migration PRはforward、rollback、既存data影響を記載する。
- 実機証跡は秘密値、個人情報、会話原文を含めない。

CIの通常運用と節目運用は[`../operations/ci-fast-and-full.md`](../operations/ci-fast-and-full.md)に従う。旧資産の整理は[`../operations/legacy-assets-inventory.md`](../operations/legacy-assets-inventory.md)を先に更新する。

## 失敗時の再計画

同じtaskがimplementation loopを三回失敗した場合、worker追加で押し切らずplanningへ戻す。

再計画では次を記録する。

- 失敗したACと最小再現command。
- contract不備、実装不備、環境不備、未知の分類。
- 既存commitとdataを壊さないrollback。
- spikeへ戻すtask ID。
- dependent taskのHOLD範囲。

同じblocking conditionが三goal turn続き、利用者入力または外部状態変化なしでは進めない場合だけgoalをblockedへ更新する。

## スコープ外

- 複数利用者、共同編集、組織権限。
- 課金、Free / Standard / Pro。
- Dots独自のDeep Research schedulerと通知基盤。
- public MCP endpointとcloud常時稼働DB。
- 汎用local chat LLMによる会話・抽出・レポート生成の全面置換。
- 未承認のembedding providerや外部reranker。検索用の固定ローカルモデルは初期要件に含む。
- Neo4j GDS structural embeddings、Text2Cypher、任意Cypher MCP。
- 自動physical delete、自動名寄せ確定、任意Cypher。
- 法務、税務、投資、融資、特許性の確定判断。

## Definition of Done

本計画は次の全条件を満たした場合だけ完了とする。

- [ ] 中心価値: 内容からentity・意味関係候補を抽出し、根拠・推測状態・訂正履歴とともに保存し、独立した別会話5組で関連資産・人物・過去案を上位5件へ返して再利用する。履歴edgeとvector類似だけでは代替しない。
- [ ] スマホChatGPTのread/writeについて、成功時のID・実保存と拒否時の発生元・未保存を実機で区別できる。host制約なら制約と本人用の手順を検証し、スマホ対応済みと偽らない。
- [ ] 本人用OpenAI接続の権限・関連付け・共有範囲とPC内アクセス境界を照合し、認証と固定ownerを区別した説明がある。意図しない外部アクセスを許さない。
- [ ] PC 1280×720でgraph→home/servicesの連続遷移、非同期読込中の遷移、描画失敗を確認し、全画面空白・未処理pageerrorが0件。semantic graphが通常表示で、内部版構造は主役にしない。
- [ ] 中継再起動後の最初の検索が3回連続成功し、上流/ローカルの未解決障害を成功扱いにしない。
- [ ] schema v2のidentity、revision、RelationAssertion、Source、Chunk契約がmainにある。
- [ ] 実Neo4jでmigration、write、read、停止、再起動、restoreが成功している。
- [ ] ChatGPT代表会話5件が合成データでIdea保存と再検索に成功している。
- [ ] Dots全体検索とResearchBriefがprivate fieldを外部へ出さない。
- [ ] 許諾済みCampaignで複数Runと8観点のIdeaBriefVersionを保存・比較できる。調査全文の製本・常設Report閲覧は、追補に従い必須としない。根拠・引用・版の履歴は保持する。
- [ ] Person、Organization、Asset、名寄せ候補、RelationAssertionを確認できる。
- [ ] 合成Person―Idea関係をChatGPT MCPからEvidence付きschema v2 RelationAssertionとして保存し、再起動後に根拠付きで検索できる。
- [ ] 固定revisionのmultilingual-e5-base/768次元 embedding、mMARCO multilingual local cross-encoder、Neo4j full-text/vector index、WRRF、最大2-hop関係展開を固定の日英・交差言語合成queryで評価し、ChatGPTから再起動前後に直接検証できる。既存の品質評価を再利用し、速度比較は繰り返さない。
- [ ] 固定20問の期待結果は実装者がテスト対象と独立に作り、100件以上の合成対象で評価する。利用者は20問を起草せず、必要なら代表結果だけ確認する。
- [ ] Windowsログイン後にDocker Desktop、Neo4j、Dots MCP、Secure MCP Tunnelが依存順で自動起動し、ChatGPTでIdea保存と再検索ができる。未ログイン・停止中は利用できない。
- [ ] ブラウザーを閉じても通常Dotsが稼働し、`localhost`の操作盤で状態・Idea/Person/Asset/Report概要を確認し、既存データを残して停止・再開できる。起動用の端末窓は残らない。
- [ ] Graph UIがlive semantic data、推測/確定、根拠、unavailableを表示し、概要の訂正・履歴と調査差分は対応するホーム/記録経路で確認できる。
- [ ] backup、isolated restore、soft delete、safe exportが同じfixtureで成功している。
- [ ] 実データcanary一件が保存、再起動、検索、backupを通過し、削除・復元の試行は許諾済みの隔離コピーだけで確認する。通常の保存データは削除しない。
- [ ] 全required CIが成功し、main smokeが成功している。
- [ ] setup、起動、停止、復旧、ChatGPT接続runbookが最新である。
- [ ] P0/P1 security、data loss、owner越境issueが0件である。

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| ADR-MP-01 execution model | subagent worker/reviewerは`gpt-6-luna / medium`を使い、root coordinatorは利用者指定環境に従う。利用者の後続指示を反映した | 未指定のfallbackや別modelへの自動切替はhandoff再解釈を増やすため却下 | active goal向けの明示override |
| ADR-MP-02 concurrency | root一枠と独立worker最大三枠にする。現在の四枠で統制と実装を両立するため | rootを含む全枠を実装へ使う案はreviewとownership管理が消えるため却下 | ready taskだけ並列化 |
| ADR-MP-03 context | task packetとartifactを正本にし、1M contextへ依存しない | 全履歴を各workerへ渡す案はtoken消費と古い指示混入を増やすため却下 | 短いhandoffを必須化 |
| ADR-MP-04 schema gate | schema v2と実機永続化gate通過後にNeo4jを既定化する | schema v1のまま既定化する案はidentityとrelation履歴が未確定のため却下 | P2-04で切替 |
| ADR-MP-05 external rollout | 合成接続、security review、一件canaryの順にする | 最初から実会話と名刺を送る案は漏えい時の影響が大きいため却下 | D-EXT-01とD-REAL-01を分離 |
| ADR-MP-06 local startup | Windowsユーザーの対話ログイン後にだけDocker / Neo4j / MCP Tunnelを自動起動し、health確認後にChatGPT接続を受ける | OS起動時の未ログイン常駐は不要な外部接続と資格情報露出時間を増やすため却下 | sleep / shutdown中はアクセス不可という利用者判断と整合 |

## 変更履歴

| 日時 | 変更 | 理由 | 影響task |
| --- | --- | --- | --- |
| 2026-09-26 | 利用者指示で実装待機。スマホ書込み拒否、本人限定の信頼境界、再現済みグラフ終了例外を追加し、意味関係の抽出・根拠保存・別会話再利用を中心DoDへ改訂。旧phaseは履歴に区分 | 接続成功と履歴graphだけでMVP完成とする誤認を解消し、実利用の故障と製品価値を同じ残計画で管理するため | RP-SP-01〜RP-10、全DoD |
| 2026-09-22 | 初版。schema v2、Neo4j実機、ChatGPT接続、Research、UI、backup、実データcanaryまでのDAGを定義 | Luna Max主体のゴールモードで実装全体を完遂できる正本が必要なため | P0-01〜P9-04 |
| 2026-09-23 | schema v2 domain contract、max 2-hop read、Neo4j/system dumpと隔離restore queryの実機証跡を反映 | 実装済み範囲と未完了のAttachment、manifest、外部接続を分離して次の作業を選べるようにするため | DM-01、P3-02、P8-SP-01 |
| 2026-09-23 | schema v2 migrationと非破壊rollbackを実装し、空DB・v1合成ノードで実機確認 | v2構造をNeo4jへ安全に追加し、既存データ変換とは分けて次のwrite/read作業へ進めるため | DM-02、P1-03 |
| 2026-09-23 | 合成MCP保存・検索・詳細取得と名刺CSV安全取込を反映 | 外部ChatGPT接続と自動名寄せを開始せず、P5/P4のローカル価値をmainで検証できるようにするため | P5-SP-01、P4-02 |
| 2026-09-23 | 合成人物のローカル名寄せ候補と上位3件評価を追加 | 連絡先を外部送信せず、本人確定前の自動統合を防いだ品質基準を固定するため | P4-SP-03-A |
| 2026-09-24 | SourceRevisionからContentChunk、Evidence、RelationAssertion、検索までの未完了経路を子計画へ分解 | 現在のMCP relation writeがv1 Relationshipであり、Evidence作成とNeo4j根拠検証がつながっていないことを監査で確認したため | P3-04、P4-04〜06 |
| 2026-09-24 | schema v2が要求するSource / SourceRevision / ContentChunk間の構造edgeと既存graphの冪等補修をEvidence作成前のgateとして追加 | 現行保存はrevision pointerだけでGraph上の出典経路をたどれず、schema v2の契約を満たしていないため | P3-05、P4-04 |
| 2026-09-24 | P3をNeo4j full-text + multilingual vector/WRRF + RelationAssertion展開 + local cross-encoderへ再定義し、ChatGPT再起動後試験をP5-03へ追加。subagent profileをGPT-6 Luna Mediumへ更新 | Luna rerankは現実的でないという利用者判断と、ChatGPTから最小Graph RAGを直接検証する要求を反映 | P3-SP-04、P3-02〜03、P5-03 |
| 2026-09-24 | 初回Neo4j 20問実測でWRRF Recall@20 0.53、HitRate@5 0.55、path/evidence coverage 0%、rerank Recall@50低下を確認。直接候補へのpath伝播・candidate保全・CJK比較をP3完了条件に明記 | モデルが上位順位を改善しても候補漏れと根拠経路欠落が残り、Graph RAGの合格を宣言できないため | P3-02、P3-SP-04、P3-SP-05、P3-SP-03 |
| 2026-09-24 | 検索モデルをSentence Transformers対応の多言語E5/mMARCOへ変更し、P3受入条件へ交差言語queryを追加 | 英語資料を日本語の問いから検索したいという利用者要件を反映 | P3-02〜03、P5-03 |
| 2026-09-24 | Graph RAGの評価を100件以上の合成対象とRecall@20 / HitRate@5へ改め、Windowsログイン後自動起動を明示gateとして追加 | 現行17対象のtop-50評価は品質を区別できず、再起動後の手動起動も利用者ゴールに届かないため | P2-05、P3-02、P3-SP-03、P5-03〜04 |
| 2026-09-24 | 初回のローカルモデル読込を含む検索上限を30秒に設定し、warm検索と別に記録する条件を追加 | 合成Neo4jで初回約11.4秒、warm約0.46秒、別smokeでE5初回load+encode約13.7秒とreranker初回load+score約4.5秒を観測し、既定5秒では初回が失敗したため | P3-SP-03、P3-03 |
| 2026-09-24 | P3-SP-05として固定検索fixture/scorerとMCP実検索評価を計画へ追加 | fixture通過だけで実hybrid retrievalやMCPの公開境界を合格扱いせず、WRRF基準順位とreranker後順位をDots上で再現可能に測るため | P3-SP-05 |
| 2026-09-24 | Neo4j Communityの単一標準DB制約に合わせ、benchmarkの隔離単位をdatabase名から一時instanceへ変更 | Community Editionでは専用の`dots-benchmark-*` DBを追加作成できないため。runnerは既定`neo4j`を明示opt-inと空確認なしに触らず、instance lifecycleは呼出側が所有する | P3-SP-05 |
| 2026-09-24 | Graph RAG監査で判明した逆向きpathの誤表示、reranker既定ON、benchmark path/evidence gate漏れを計画へ追加 | 事実と逆向き関係を誤表示せず、測定前の順位変更と根拠欠落を合格扱いしないため | P3-SP-06、P3-SP-05、P3-SP-03 |
| 2026-09-24 | 合成benchmarkでseed上限とgraph score decayを比較し、decay 1.0がpath/evidenceを改善する一方、候補上限拡大ではrecallが改善しないことを追記 | スコア調整だけで検索gateを満たしたと誤認せず、候補作成時の漏れを別に調べるため | P3-SP-05 |
| 2026-09-24 | Source構造edgeの全体repair preview/applyを両adapterへ実装し、41 focused / 543 backend testsを確認。既存DBに対するlive実行は認証経路と再起動試験待ち | repairは検査後に不足edgeだけ追加し、矛盾時の変更・既存edge削除を避けるため | P3-05、P4-04 |
| 2026-09-24 | disposable Neo4j実機smokeでpayload文字列の部分一致による誤検知を修正し、preview無変更、missing edge 1件だけ追加、反復時missing 0、audit差分0を確認 | fake driverでは見えなかった、本文中の出典IDを別種nodeとして扱うクエリ誤検知を防ぐため | P3-05 |
| 2026-09-25 | repair候補をpayload内の実参照欄で再確認し、本文中にIDがあるだけの無関係な外国データとSourceRevision IDを持つcapture-auditを除外。一方、型付き参照がlocal graphへ向く異常nodeは型/label不整合でも停止する。29 focused / backend 556 passed, 2 skipped。fresh loopback-only Neo4jで欠損1件のpreview/apply/repeat=0を再確認 | 独立レビューと実機診断で、誤検知候補とaudit metadataのproperty衝突が見つかったため。既存ChatGPT用DBにはアクセスせず、修復対象の選別を閉じる | P3-05 |
| 2026-09-25 | schema v4のfresh disposable Neo4jで実MCP検索のreranker候補数10/20/40を比較し、20をopt-in時の候補数に採用。benchmarkがschema v4を3と誤記する問題を修正し、以降はアプリ定義のschema versionを出力 | 40件は遅く、10件は順位改善が弱い一方、20件はwarm p95 4.393秒とnDCG/Hit@5改善を両立。ただしWRRFのrecallとpath/evidence coverageは合格基準未満 | P3-SP-03、P3-SP-05 |
| 2026-09-25 | 20問の速度比較を同一DB内の5反復・固定seed順・paired設計へ拡張し、標本標準偏差、質問別統計、WSL負荷記録を受入条件に追加。fixtureの質問文20件も計画に掲載 | 各質問1回ずつの比較ではPC負荷と質問差を分離できないため。従来の「40件」は20問をbaseline/rerankerで一度ずつ測った40検索呼出で、40種類の質問ではない | P3-SP-07 |
| 2026-09-25 | 一回限りの300件warm paired測定を完了。baseline 0.707±0.200秒、候補20 3.493±0.679秒、候補40 6.342±1.138秒（各100標本）。WSL load averageは測定中に上昇し、絶対速度から外部PC負荷だけを分離できないと記録。以後はモデル・検索経路変更等の特別な理由なしに再測定しない | 利用者指示により標準偏差と負荷条件を記録しながら、一回の基準比較後の通常開発で長時間ベンチを繰り返さないため | P3-SP-07 |
| 2026-09-25 | Neo4jの`unless-stopped`が補うのはDocker Engine起動後のコンテナ再開だけであり、Windowsログイン後のDots MCP/Tunnel起動を含まないと全体計画を明記 | Compose restart policyを全体の自動起動と誤認せず、P2-05 / P5-04の残作業を分離するため | P2-05、P5-04 |
| 2026-09-25 | synthetic tunnelのdoctorは通る一方、実MCP呼出しはセッション終了し、stdio子プロセスが終了する状態を確認。現在のprofileにはNeo4j認証情報の安全な受渡し方法がなく、runtimeも認証ファイルを読めない。保護済みファイルから`neo4j/<password>`を読むruntime契約と、欠落・symlink・不正形式の拒否を先に実装する | 合成DBの接続パスを直し、password本文をprofile、引数、ログ、Gitへ保存せずにMCP接続を復旧するため。既存live DBやユーザーデータの資格情報は変更しない | P5-04 |
| 2026-09-25 | ログイン自動起動を、検証用synthetic volumeと通常利用のlive volumeに分離。P5-04は前者だけを対象にし、Docker Desktop公式CLIとWindowsログオンタスクからWSL Tunnelを起動、本人のWinlogonログオフ通知で停止する。明示停止した合成DBは自動で再開せず、通常DBの資格情報ローテーションと起動gateはP2-05に残す | ChatGPTとの再起動後検証を安全な合成データだけで先行し、通常データの秘密情報・保存先を混同しないため | P2-05、P5-03〜04 |
| 2026-09-25 | ログオンtask終了後70秒の無操作でUbuntu distroとTunnelが停止することを再現し、systemd serviceだけではWSLが起動状態を保てないMicrosoft仕様と整合した。Tunnel稼働中はログオンtaskを低負荷の待機プロセスとして維持し、無操作70秒後もUbuntu/Tunnelが稼働することを確認。手動でログオフtaskを実行するとresult 0でTunnel停止と待機task終了、65秒後にUbuntu停止。明示停止したsynthetic DBは起動されずTunnelもinactive。DB停止/再開後もChatGPTからcapture/search/fetchでき、同一idempotency key再送は同じIDへreplay。実際のWindowsログオフ通知とWindows再起動試験は未了 | ChatGPT接続の起動、稼働中維持、停止、DB再開後の永続性を合成データで検証し、未実施のホスト再起動試験を明確に残すため | P5-04 |
| 2026-09-25 | 通常利用Neo4jへschema v1→v5を適用し、既存Idea 3件・FounderGraphAudit 3件を変更せず一意制約/CJK full-text/vector indexをONLINE化。ChatGPT既存接続のtool listを更新し、合成Ideaを保存・検索・詳細取得、合成Neo4j container再起動後も同じcanonical IDとtitleで検索/取得できることを実証。Metadata-only Assetの保存/検索/取得、Personのdefault local_only非返却、明示shareable時のidentity-only projectionを合成データで確認。backend 602 passed / 2 skipped | 最初のChatGPT→Dots→再起動後検索の一本道と、Asset/Person egress境界の実動作を証明し、通常利用Neo4j schemaとsynthetic ChatGPT経路の進捗を分離して記録するため。Windows実再起動、通常API/MCPのログイン起動、Graph RAG品質gateは継続 | P2-05、P5-SP-01、P5-03、P5-04 |
| 2026-09-25 | ChatGPTから合成Person→Idea RelationAssertionを期限・Evidence付きで保存し、search pathとmetadata-only Evidence fetchをNeo4j container再起動の前後で確認。MCPの共通WriteReceipt outputSchemaを追加し、ChatGPTによる返却IDの引継ぎを試験する計画を子計画へ追加 | persistence gateの「人物と何をするか」を含むpathまで実機証明できたため。また、ChatGPTがIDを次のtoolへ渡せず手作業になった実機問題を、MCPの型付き結果契約として切り分けるため | P5-03、GR-WR-06、GR-WR-SP-01 |
| 2026-09-25 | 全11個のMCP write toolへ共通receipt outputSchemaを追加。ChatGPT接続を更新し、新規会話で合成Ideaを保存し返却IDを手入力せずfetchへ渡して、同じtitleが返ることを確認。全backend 613 passed / 2 skipped、diff check passed | ChatGPTの会話だけでDotsへの記録と後続参照がつながることを、実データなしで確認するため | P5-03、GR-WR-06、GR-WR-SP-01 |
| 2026-09-25 | 合成フルフローがIdea / Personの保存後にClaim分類値`opportunity`で停止したため、`append_claim`のschemaをdomain enum 4値に制限し、4値の保存と無効値で無書込みになるfocused regressionを追加。全backend 614 passed / 2 skipped | backendはClaim分類を4値に制限していた一方、ChatGPTへ公開するschemaが自由文字列のため、自然だがdomain外の分類が選ばれた。モデルが使える値だけをtool discoveryへ示し、誤入力を未然に防ぐ | P5-03、GR-WR-07 |
| 2026-09-25 | 通常Chatの一回の合成発話でIdea / Person / Claim / ADDRESSES / Evidence / CAN_CONTRIBUTE_TOを各write receiptのIDで連鎖し、関係検索とEvidence fetchを確認。CAN_CONTRIBUTE_TO / proposed / confidence 0.82 / 2027-12-31T23:59:59ZとEvidence IDが一致。Evidence詳細はpolarity・confidence・statusのみでsource/chunk本文・locator・連絡先・private_notesなし。shareable Ideaのsummary/snippetは仕様どおり検索結果に含まれた | ChatGPTからDotsの一連の書込みと根拠付きGraph RAG読出しを、一度の自然文指示だけで通すため。代表会話5件・Windows再起動後の試験・Graph RAG品質gateは引き続き未完了 | P5-03、GR-WR-SP-01 |
| 2026-09-25 | 合成接続へ品質合格済みE5-base / mMARCO候補40件を可逆に適用する工程を、モデル準備・別索引・合成service設定へ分割。通常384次元indexとsmall既定を維持する | 固定20問では候補構成の順位品質が合格した一方、合成接続の実行構成は未変更だったため。Windows再起動前に実際の利用経路へ反映する | US-MP-06、P3-SP-17A〜17C |
| 2026-09-25 | 合成Dotsを選んだ自然な創業案からIdeaが保存され、別会話とMCPの検索・取得で同じ記録を確認。類似案では検索のみ観測。利用者はMVPでメッセージごとのDots選択を許容し、選択後の暗黙記録を希望。ChatGPT側の表示名と接続名をDotsへ変更し、合成専用の説明を維持 | 自然会話の保存と既存案の重複回避を別々に評価し、選択不要の全会話自動記録をMVP達成と誤認しないため | US-MP-07、P5-01、P5-NC-01 |
| 2026-09-25 | 利用者が安全確認後の通常利用DotsとChatGPTとの読み書き接続を承認。合成接続の許可とは分け、通常Neo4j認証情報の交換、個人連絡先・非公開メモ・資料本文の非共有検査、通常用の独立起動経路を先行gateとする | 実データが外部ChatGPTへ使われる境界を本人の意思決定で固定し、合成・通常のvolume混同を防ぐため | P2-05、P5-03〜04、P9-01 |
| 2026-09-25 | 合成の自然会話から小売実験Idea・架空Person・期限付き貢献関係を保存し、MCP再検索で双方と関係を確認。通常接続前監査で、共有設定が誤ったSourceRevision / ContentChunkがMCPに出せる欠陥を検出し、型ベースの拒否と検索・詳細取得の回帰テストを追加。全backend 680 passed / 2 skipped。稼働中synthetic serviceの再起動と通常接続は別gate | 自然会話の人脈活用を実証しつつ、実データの本文が設定ミスで外部へ出ない境界を先に固めるため | P5-01、P5-03、P9-01 |
| 2026-09-25 | 通常用liveログオンpreflight / 登録コードと、別MCP service template / owner・volume・port・認証ファイルguardを実装。前者はPester 11/11、後者はfake tests 70件成功。どちらも実登録・実接続はしていない。使い捨てNeo4jでfile-secretのrunning containerへの反映と旧fake値への同一container復旧、再作成後のvolume / marker維持を確認し、専用資源は残存0件で撤収。実DB password変更と資格情報rotationは未実施 | 合成接続を通常データへ流用せず、鍵交換時のDocker挙動を実データに触れる前に検証するため | P2-05、P5-LIVE-01、P9-01 |
