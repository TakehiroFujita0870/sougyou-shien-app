# メモリ正式関係の検索・読取整合性計画

最終確認日: 2026-09-26

## 目的

メモリグラフの検索で、保存済みの正式な`RelationAssertion`を意味上の辺としてたどり、実在する関係IDと根拠情報を保つ。読取側だけの変更であり、Neo4jや外部MCP/UIへの公開は有効化しない。

差分目標は500行以内。今回のみ、root承認により意味を弱めない単一メモリ読取packetとして560行までを許容する。超過時は実装を止め再計画する。

## 利用者ストーリーと受入条件

### US-1 — 根拠付き正式関係を検索する

本人として、検索経路に保存済みの正式関係を実際の両端間の意味ある辺として表示し、根拠と保存構造を区別したい。

Given: メモリwriterが、所有者が一致する`RelationAssertion`、正規の`ASSERTS_FROM`/`ASSERTS_TO`/`EVIDENCED_BY`参照、現行の両端、同一所有者の有効なEvidenceを一体で保存している。Idea端点がある場合は、writerの既存規則に従い、sourceがIdeaならsource、そうでなければtargetを主Ideaとして、そこに対する最新の調査済みBriefの選択章を参照している。

When: `GraphReadService.search`がメモリグラフを検索する。

Then: `SearchHit.relation_path`の一段がsourceとtargetを直接結び、実際のassertion ID、述語・方向、状態、確信度、有効期間、Evidence ID、該当時は主Ideaに対する正確な最新Brief IDと章番号を持つ。選択Brief章の本文は空白のみでなく、Evidenceを含むこと。Assertionノードや`ASSERTS_*`/`EVIDENCED_BY`/`SUPERSEDES`の足場は、意味上の端点・述語として返らない。

### US-2 — 旧版・不正・安全でない経路を除外する

本人として、不正または旧版の正式関係をpayloadから推測せず、検索経路から除外したい。

Given: assertionの所有者・端点型・状態・期間が不正、端点またはEvidenceが非現行、正規参照に欠落・重複・不一致がある、同一所有者の後継がある、または主Ideaの最新Briefが参照Briefより新しい。

When: 検索が意味上の隣接関係を組み立てる。

Then: 不正なassertion経路は返らず、構造参照が不正なときpayloadの端点やEvidence IDで補完しない。後継のpayload `supersedes_id`または正規`SUPERSEDES`辺のいずれかが同一所有者の先行assertionを指せば、後継状態を問わず先行関係を除外する。後継が複数なら旧関係を戻さず、曖昧な後継pathも返さない。別所有者の後継は影響しない。旧関係の通常取得・履歴動作は変更しない。

### US-3 — 旧形式読取を保ち、IDを捏造しない

既存の旧形式`Relationship`利用者として、正式関係に正確なIDを加えても従来経路は変えたくない。

Given: 既存の`relations()`経路が旧形式の関係を返す。

When: 検索が経路を組み立てる。

Then: 述語・方向・Evidenceの従来動作を保ち、`relation_assertion_id`は`None`のままにする。端点が一致するだけで正式assertionを生成しない。

## 対象範囲

- `backend/dots/founder_graph_write.py`: `InMemoryGraphWriteService.read_snapshot() -> GraphReadSnapshot`。frozen値が保存済みnode、旧形式relation、正規構造辺、Brief値をtupleで保持する。既存lock内で一括生成し、汎用GraphWritePortには追加しない。foreign値が混在した場合にread側がowner境界を検証できるよう、snapshot生成時にowner判定で黙って捨てない。
- `backend/dots/founder_graph_read.py`: 一つのスナップショットから正式関係の意味上の隣接関係を作る。
- `backend/tests/test_founder_graph_assertion_read.py`: 合成メモリfixtureのみを使った新規重点テスト。
- 本計画に完了した検査結果を追記する。
- 別々の`nodes()`、`relations()`、`structural_edges()`、Brief getterを合成せず、read側からwriterのmutable内部辞書を直接読まない。
- `ASSERTS_FROM`と`ASSERTS_TO`はそれぞれ正確に一件を要求する。構造上のEvidence IDはAssertionの保存IDと完全一致し、重複・別所有者・欠落・非現行Evidenceがないこと。端点のowner、宣言型、現行状態、有効期間も検証する。
- 端点のIdeaはsourceとtargetの両方について現行版を確認する。一方、Brief参照はwriter既存規則どおり一つだけ選ぶ（sourceがIdeaならsource、そうでなければtarget）。そのIdea系列の最新Brief、正確な`based_on_idea_id`、章の存在、章へのEvidence掲載を確認する。targetにも別のBriefを要求しない。
- 新しいBriefが保存されたら、旧Briefに基づく関係pathは現行検索から外す。古いassertionとBriefは履歴から削除しない。Run実行後に許諾が期限切れ・取消されても、最新の受理済みBriefに紐づく関係について現行authorization validatorを再実行しない。
- 先行関係を隠す判定では、同一ownerの後継Assertionのpayload `supersedes_id`または後継から先行への正規`SUPERSEDES`辺のどちらかを根拠にする。後継状態を問わず旧関係を抑止し、破損後継で旧関係を復活させない。後継自身のpathはpayloadと正規辺の完全一致かつ先行に対して一件だけであることを要求する。別ownerの後継は無視する。
- 既存`Relationship`投影は独立して保ち、正式Assertionへの変換wrapperは作らない。

## 対象外

- Neo4j保存・型付きhydration、schema、gateway/port、正式writeの変更、MCP/UI/API投影、runtime/service/DB操作、benchmark、調査/許諾workflow変更。
- direct fetchの再設計や新しい履歴検索API。履歴は既存writer/history経路で扱い、通常検索だけを変更する。

## タスク

| ID | 成果物 | 完了判定 | 不確実性 |
| --- | --- | --- | --- |
| P4-05-MEM-READ-01 | `GraphReadSnapshot`、lock内`read_snapshot()`、`founder_graph_read.py`の正式path投影、新規focused tests | 検査: 正例Idea→Claimで実assertion/Evidence/最新Brief参照を保持。新Brief保存後は旧pathを除外し、後日の許諾期限切れは受理済みBrief pathを遡及無効にしない。両Idea端点が現行であること、主IdeaのみBriefを要求することを検査。壊れた正規参照、端点/Evidence/owner/時刻/status、空章、同一owner後継（status不問・複数後継）、別owner後継の負例を検査。write途中のreaderが一貫snapshotを得ること、旧形式の互換とID非捏造、focused/backend全suite、diff checkを確認。TDD: formal path/snapshot初回3 failed、空章回帰red1→green1、read/write focused 37 passed、main 09f4d4e7f048後backend 766 passed/4 skipped、diff-check clean。 | 完了 |

## 質問リスト

なし。範囲と現行性規則はmaster planおよびrootの承認済み境界で確定済み。

## ADR

| 判断 | 採用・理由 | 却下案・理由 | 結果 |
| --- | --- | --- | --- |
| 一貫したread snapshot | 既存writer lock中にfrozen tuple snapshotを作り、node/構造辺/最新Briefの混在を防ぐ。 | getterを個別に呼ぶ案は、異なるrevisionを合成し得るため却下。private dictをread側で直接走査する案も責務境界を破るため却下。 | memory read adapterのみ変更。 |
| 正式Assertion path | typed assertionとcanonical structural refsの一致を検証し、実ID・保存metadataを返す。 | payloadからendpoint/Evidenceを再構成する案はcanonical refsと食い違い得るため却下。 | 構造不整合時はfail-closed。 |
| 現行性・後継 | 現行statusは`proposed`/`inferred`/`confirmed`とし、validity期間、owner、両端とEvidenceを確認。同一ownerのpayload `supersedes_id`またはcanonical `SUPERSEDES`辺があれば、片方が不一致でも旧関係を抑止。後継path自体はpayload・構造辺の完全一致時だけ返す。 | successor statusが非現行なら旧関係を復活させる案は却下。foreign ownerのsuccessorによる抑止も却下。 | 履歴は残し、通常検索からだけ除外。 |
| IdeaとBrief参照 | 両Idea端点のcurrentnessを確認する。BriefはsourceがIdeaならsource、そうでなければtarget一件だけを主Ideaとし、その系列の最新Brief・正確な章・Evidence掲載を要求。 | 両端IdeaそれぞれにBriefを要求する案、過去accepted Runのauthを検索時に再検証する案は却下。 | 新しいBriefができたら旧Brief参照の関係は更新まで現行検索に出さない。後日の許諾変更で受理済みRunの証明を遡及変更しない。 |
| 旧形式relation | 既存`Relationship`pathをそのまま維持し、`relation_assertion_id=None`を保つ。 | 端点だけでAssertion IDやformal pathを生成する案は却下。 | 互換wrapperなし。Neo4j/MCPはこのpacketの対象外。 |

## 変更履歴

| 日付 | 変更 | 理由 | タスク |
| --- | --- | --- | --- |
| 2026-09-26 | 一貫snapshotと最新Brief現行性を含む、メモリ正式関係の検索・読取整合性計画を作成。 | 現行main 09f4d4e7f048（#273後）の読取・正式writer境界を再確認し、merge後の全backend検査を記録。 | P4-05-MEM-READ-01 |
