# RelationAssertion brief参照 計画

最終検証日: 2026-09-26

## 要望 / ゴール / 成功指標

要望: RelationAssertionに、根拠となったIdeaBriefVersionとその章を任意で記録できるようにする。

ゴール: 既存のRelationAssertionを壊さず、brief IDと8章の0始まり位置を対で保持できるdomain契約を定める。

成功指標: domainテストで旧形式と有効な境界値が受理され、不完全な参照・不正な章番号・不正なIDが拒否される。

## ユーザーストーリーと受け入れ条件

### US-1

As a Founder Graph reader, I want a formal relation to optionally point to the exact brief section it came from, so that later provenance work can resolve that context without guessing.

Given: brief参照を持たない既存RelationAssertion、または有効なbrief IDと章番号0〜7がある
When: RelationAssertionを生成する
Then: 旧形式は両参照がNoneのまま受理され、有効なペアは値を保持して受理される

Given: brief IDと章番号の片方だけ、空ID、または整数でない/範囲外の章番号がある
When: RelationAssertionを生成する
Then: DomainValidationErrorで拒否される。boolは整数として扱われない

## スコープ外

- Neo4j保存形式、読取projection、MCP/API、検索・provenance表示の変更。
- briefの存在、owner、最新revision、調査完了の確認。
- 既存保存データの移行。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| RP-04D3A | RelationAssertionの任意のcoupled brief/section domain fieldsとfocused tests | 検査: `uv run pytest -q tests/test_founder_graph_relation_brief_reference.py` | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| brief provenanceのdomain表現 | `based_on_brief_id` と `based_on_brief_section_index` を任意の対として追加し、両方ある場合のみ0〜7を許可する。既存値の後方互換性を保ち、将来のread/write層に正確な章位置を渡す | brief本文をRelationAssertionへ複製する案は履歴重複とprivate本文の不要な流通を招くため却下 | domain/testのみ。永続化・APIは後続packetで別途検討 |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-09-26 | RP-04D3Aのdomain受け入れ条件とrollback境界を追加 | relation provenance参照の最小契約を実装前に固定するため | RP-04D3A |

## ロールバック

このpacketのdomain field/validationとfocused test、計画文書を同時にrevertする。永続化やschema変更を含まないためDB操作は不要。legacy RelationAssertionの両field未指定時は従来動作を維持する。
