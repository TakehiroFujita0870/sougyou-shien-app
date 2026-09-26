# 永続ResearchRunの厳格な読み取り計画

最終検証日: 2026-09-26

## 要望 / ゴール / 成功指標

要望: Brief保存処理が永続Runを権威ある根拠として検証できるよう、現在の汎用読み取りで不透明参照に留まるResearchRunを、欠落・矛盾・不正値を成功扱いしない方法で復元する。

ゴール: owner-scopedな保存Run projectionから全フィールドを損失なく型付きResearchRunへ復号し、証明に使えない保存状態を固定エラーでfail closedにする。

成功指標: 完全なsynthetic payloadは元Runと同値に復号でき、identity/type/revision/field/timestamp/enum/provenance/snapshotのいずれかが欠落・不正なpayloadはResearchRunとして返らない。

## ユーザーストーリーと受け入れ条件

### US-1

As a owner-scoped Brief writer, I want persisted ResearchRun records strictly hydrated, so that authorization and run-registration checks consume typed persisted facts rather than permissive dictionaries.

Given: Neo4j gatewayのbounded `fetch_node_record` projectionに正しいrun id、owner、node type、metadata revision 0、完全なserialized ResearchRun payloadがある。
When: strict decoderへ期待ownerと期待run idを渡す。
Then: payloadに格納された各fieldを保持するtyped ResearchRunが返り、既定idや現在時刻を新たに生成しない。

Given: record identity、node_type、revision、payload field set、nested provenance、timestamp、enum、list、snapshot mappingのいずれかが欠落・矛盾・不正である。
When: strict decoderで復号する。
Then: 固定のResearchRunDecodeErrorで失敗し、partial/default-filled Runを返さない。

Given: Run payloadのJSONに重複object key、非有限数、またはResearchRunが持たない余分なfieldがある。
When: strict decoderで復号する。
Then: 後勝ち上書きや未知fieldの破棄をせず失敗する。

## スコープ外

- Neo4j gateway query、`Neo4jGraphWriteService.get_node`、Protocol、MCP/API、runtimeの接続。
- Idea、Brief、Campaignの新decoderとDB migration。
- decoder内でのResearchCampaign許諾、Run receipt、`HAS_RUN`、Brief最新性の検証。呼出側が別途権威ある登録状態として照合する。
- completed以外のRun statusをHydration段階で拒否すること。authorization consumerが用途に応じてstatusを検査する。
- 実DB、通常service、既存保存データの変更。

## 現状と保存契約

`_node_properties`はResearchRunをdataclass全fieldのJSONとして`payload_json`へ保存する。Enumはvalue文字列、datetimeはISO文字列、MappingはJSON object、tuple/listはJSON arrayとなる。ResearchRun自身は`revision`を持たないため、外側のNeo4j metadata revisionは`_node_revision`により0となる。外側のbounded `fetch_node_record`は `id, owner_id, node_type, revision, payload_json` を返す。

現行`_payload`はouter owner、type allowlist、payload JSON object、payload/recordのidとownerだけを確かめる。`get_node`はRunの全payloadを`PersistedNodeReference.fields`へ保持するが、ResearchRunへhydrateしない。よってenum、nested mapping、timestamps、provenance、必須field set、unknown field、Run型固有のinvariantは型付きauthorization evidenceとして保証されない。既存Correction hydratorの`_provenance`は欠落したactor/operation/origin/`idempotency_key`をdefaultで補い、`_timestamp`はnaive timestampを拒否しないため、そのまま再利用しない。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| P4-05-RUN-DEC-SP01 | `_node_properties`のRun serialization、全domain field、record metadata、既存read/hydrationの欠落・default動作をread-only確認 | 検査: `ResearchRun`に独自revisionがなくouter revision 0であること、保存JSONのfull field set、provenance/retry/map/timestamp形式、`get_node`がtyped Runを返さないことをコード上で確認し本計画へ記録。 | 完了: `founder_graph.py`、`founder_graph_neo4j.py`、`founder_graph_neo4j_write.py`を読み、Run dataclassと`_node_properties`/`fetch_node_record`/`_payload`/`get_node`の対応を確認。DB/service不使用。既知 |
| P4-05-RUN-DEC-01 | `backend/dots/founder_graph_neo4j_run.py` と `backend/tests/test_founder_graph_neo4j_run_decoder.py` のpure strict decoder/test、及び本計画 | 検査: `decode_persisted_research_run(record, *, owner_id, expected_id) -> ResearchRun` がbounded record metadataとpayloadのid/owner/node_typeを一致させ、outer revisionをboolでないint 0に限定する。payload keysはResearchRun dataclass field集合と完全一致し、未知/欠落fieldを拒否。timestampsはtimezone必須ISO、nullable fieldのみnull可。status、egress_policy、provenance originはenum allowlist、authorization_revisionはnull又はboolでない正整数。ProvenanceとTransportRetryのnested key setはそれぞれdataclass全fieldと完全一致。input_snapshot/resultsはJSON objectとして再帰的なstring key・finite JSON valueだけを許し、重複JSON keysを拒否する。constructorのDomainValidationError/TypeError/ValueErrorをResearchRunDecodeErrorへ固定変換する。constructor後に全fieldの値を保存値と照合し、timestampだけはtimezone表記の異なる同一瞬間を許す。空白がtrimされるpayload/record IDやcampaign/reference文字列も拒否する。synthetic `_node_properties`由来のroundtrip、field保持、各壊れ方のfail-closedをfocused testsで検査。`uv run pytest backend/tests/test_founder_graph_neo4j_run_decoder.py -q` 34 passed、全backend `uv run pytest backend/tests -q` 730 passed / 3 skippedで検査。 | 完了、類推可能（保存側serializationとstrict Campaign decoderに基づくpure decoder） |

最新再確認（2026-09-26、main `2cb1ddac8648` を含む）: focused decoder tests 34 passed、全backend tests 732 passed / 4 skipped / 7 warnings、`git diff --check` clean。

## decoder contract

新moduleは`ResearchRunDecodeError(ValueError)`と次の単一入口を持つ。

```python
decode_persisted_research_run(
    record: Mapping[str, Any], *, owner_id: str, expected_id: str
) -> ResearchRun
```

`record`は`fetch_node_record`のowner-scoped projection形式とする。metadataの`id`は`expected_id`、`owner_id`は呼出側owner、`node_type`は`research_run`、`revision`は正確に整数0と一致し、JSON payload内の`id`/`owner_id`も同じ値でなければならない。ResearchRunにdomain revisionを追加しない。

payloadの許容keyは現在のResearchRun全dataclass fieldだけ。`input_snapshot`と`results`の各値はdomainの凍結JSON規則に従い、Mapping、配列、null、string、bool、整数、有限floatのみ許す。`sources`、`evidence_ids`、`failures`、`transport_retries`はJSON arrayであり、省略や単一stringからの暗黙変換を許さない。`started_at`/`finished_at`はnullを許すが、値があればtimezone付きでなければならない。Provenance全field、TransportRetryの`attempted_at`と`error`を保存値から復元し、既定時刻・既定idを生成しない。constructor後は全fieldを保存値と照合し、domain `_identifier`/`_text`によるtrimなどのsilent normalizationを拒否する。ISO timestampだけはtimezone表記の異なる同一瞬間を許す。Run id、owner、campaign、parent/supersedes、provenance target/source、source/evidence array stringなど、正規化され得るID/reference textも完全一致が必要である。ResearchRunのdomain constructorはshapeを検証するが、Run status、登録receipt、`HAS_RUN`、authorization proofはこのdecoder単独の責任ではない。

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| decoder location | Campaign strict decoderと同じNeo4j private hydration層に置く専用`founder_graph_neo4j_run.py` | permissive `_hydrate_correction`を拡張すると他node hydrationへscopeが広がる | Run復号境界を独立focused testで検査できる |
| metadata | owner-scoped recordのid/owner/type/revisionとpayload identityを厳密照合し、Run外側revisionは0固定 | `record.get(..., default)`やrecord欠落fieldのdefault化は不整合を隠す | 旧/壊れたrecordはauthorization evidenceとして使えずfail closed |
| payload decoding | field set完全一致、nested objectのduplicate key拒否、aware timestamp、明示enum・map/list validation | dataclass defaultや既存read hydrationは欠落値を補い、フィールドを失ったRunを返し得る | serialization contract変更は新decoderテストを伴う明示変更が必要 |
| responsibility split | decoderは完全性とtyped hydrationのみ。T02 callerはstatus/receipt/HAS_RUN/Campaign historyを検証 | decoderがRunを自動的にauthorized/completedと見なす | typed recordとauthorization proofを混同しない |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-09-26 | T02が必要とするstrict persisted Run decoderの境界、保存projectionのfield mappingとfocused acceptance casesを計画 | 現行Run get_node projectionはraw fieldsしか返さず、欠落nested metadataをdefault補完する既存hydratorを証明に流用できないため | P4-05-RUN-DEC-01 |
| 2026-09-26 | private `decode_persisted_research_run`とpure testsを追加。TDD初回はmodule未作成によるimport error、実装後はroundtrip・identity/field/type/timestamp/provenance/snapshot/duplicate-key/nonfinite/normalization拒否を検査 | 保存payloadをtyped Runへ復元しても値・refs・provenanceをsilent normalizationやdefault生成で変えず、authorization proofの前提となる完全性を確保するため | P4-05-RUN-DEC-01 |
