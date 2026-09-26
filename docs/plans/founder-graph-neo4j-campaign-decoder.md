# Neo4j Campaign payload decoder 計画

最終検証日: 2026-09-26

## 要望 / ゴール / 成功指標

要望: Neo4jに保存されたResearchCampaign payloadをowner/type/revision/enum/time検証後に安全に型復元する小さな独立単位を先に用意する。

ゴール: atomic ResearchRun writerから再利用できる、fail-closedなCampaign decoderを追加する。

成功指標: 承認済みCampaignを正確に復元し、payloadまたはrecordのowner/type/revision、未知field、enum、timestamp、provenanceが不正ならraw値を露出せず拒否する。

## ユーザーストーリーと受け入れ条件

### US-CD-01 — 保存Campaignの安全な復元

As a local Founder Graph owner, I want persisted campaign records decoded as a validated typed value, so that later writes can enforce authorization from the authoritative stored Campaign.

Given: record metadataとCampaign payloadがowner、node type、aggregate revisionを含み、列挙値とtimezone付きtimestampがモデル契約に合う。

When: `decode_persisted_research_campaign(record, *, owner_id=...)`を呼ぶ。

Then: 認可済みCampaignのstatus、snapshot、scope、予算、revision、timestamp、provenanceを保持した`ResearchCampaign`が返り、内部hydration guardは解除済みとなる。

### US-CD-02 — 不正な保存値の拒否

As a local Founder Graph owner, I want malformed or cross-owner persisted data rejected without exposing its contents, so that database corruption cannot become trusted authorization state.

Given: owner/type/revision不一致、未知または不足field、authorized/authorization_revisionの型違い、内部guard改変、不正JSON、enum、timezoneまたはprovenanceがある。

When: decoderを呼ぶ。

Then: sanitized `CampaignDecodeError`となり、例外文字列に保存payload値を含まない。

## スコープ外

- Gateway/adapterへのdecoder接続とatomic Run transaction。別の依存packetで実装する。
- Protocol、MCP、Campaign history migration、real Neo4j、通常DB、runtime/service、既存データ書換。
- 過去のmetadata-only historyから完全な認可snapshotを推測すること。

## タスク

| ID | 成果物 | 完了判定 | 不確実性 |
| --- | --- | --- | --- |
| T-CD-01 | 独立payload decoder module | 検査: typed Campaign成功とowner/type/revision/field/enum/time/provenance破損を直接テストし、raw payload非露出を確認 | 類推可能 |
| T-CD-02 | focused testsと本計画 | 検査: 専用pytest、計画Exit Criteria、`git diff --check`が成功し、追加差分500行以内 | 類推可能 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| hydration guard | payload内の`_internal_transition`は存在時に厳密なfalseだけ許可し、decoderがtrusted Campaignを構築する瞬間だけ内部遷移を有効化して直ちにfalseへ戻す。既存モデルの承認経路制約を保ったまま永続値を復元するため。 | guardをpayload値から受け入れる案は、保存payloadが通常のapprove経路を迂回できるため却下。 | 未知field、guardのtrue/非boolは拒否する。 |
| エラー内容 | 保存文字列やenum値を例外に埋め込まず、固定メッセージの`CampaignDecodeError`へ変換する。 | JSON/parsing例外をそのまま伝搬する案は保存値を露出し得るため却下。 | 呼出側は安全な拒否理由だけを受け取る。 |
| 分割境界 | decoder moduleと直接契約テストだけを先行させ、Gatewayは次packetでこれを呼ぶ。 | decoder・writer・fake suiteを同packetに含める案は500行目安を超えるため却下。 | adapter統合はdecoder review後の依存packetとする。 |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-09-26 | Run writer packetが793行となったため、Campaign decoderを独立し、追加範囲を直接テストへ限定 | 500行目安を守り、認可payload復元をwriter transactionから分離してレビュー可能にする | T-CD-01〜02 |
| 2026-09-26 | Reviewで判明したdataclass既定値による欠落payload補完を拒否し、Campaign/Provenance必須keyとauthorization primitive型の直接検査を追加 | 保存済み認可情報が不足fieldから再生成されないようにする | T-CD-01〜02 |
