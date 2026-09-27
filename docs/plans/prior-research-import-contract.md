# 過去調査の出典取込契約
最終検証日: 2026-09-27

## 要望 / ゴール / 成功指標

要望: 利用者が実施済みと確認した過去の外部調査について、元の回答に実際に表示された引用と根拠を通常の保存先へ取り込み、別会話と画面から再利用できるようにする。過去の調査を未調査とは表示せず、現在のCampaign許諾下で行われたRunとも偽らない。

ゴール: 既に保存済みのSource/Claim/Evidenceと、元回答から確認できた公開引用を、明示的な過去調査由来メタデータを持つBrief後継版へ安全に結び付ける。

成功指標: 保存後のMCP・Home読取りで、Briefの8章引用と公開根拠のURL・題名が一致する。状態表示は過去調査由来と現行Campaign/Runによる調査完了を区別する。既存のIdea・Brief版は変更せず、原調査時刻や許諾を証拠なしに補わない。

## ユーザーストーリーと受け入れ条件

### US-1 過去調査を正確に取り込む
As a 創業者, I want 実施済みの過去調査の出典を保存する, so that 元の根拠を次の会話でも確認できる。
Given: 利用者が外部調査を実施済みと確認し、元の回答に実際に表示された公開URL・題名・出典に対応する短い要約と章との対応を確認できる。
When: Dotsが過去調査取込として保存する。
Then: Brief引用は既存の公開Source/Claim/Evidenceと対応し、確認できたURL・題名・章だけを含む。Briefには取込由来と現在の保存時刻を記録し、原調査時刻が分からなければ不明のままとする。RunまたはCampaign承認履歴を作らない。

### US-2 取込状態を誤認させない
As a 創業者, I want 過去調査の取込状況を区別して見られる, so that 保存漏れと未調査、現行Run完了を混同しない。
Given: 過去調査取込記録のあるBriefと、Campaign/Runによる調査済みBriefがある。
When: HomeまたはMCPで概要を取得する。
Then: 過去調査由来のBriefは由来表示で現行Runによる`researched`と区別される。引用不足・非公開・旧版の既存状態判定は維持し、過去調査由来を未調査へ誤変換しない。

### US-3 取込を安全に再送・訂正する
As a 創業者, I want 取込操作を安全に再送・訂正する, so that 元版を失わず誤りを修正できる。
Given: 同じ取込要求の再送、競合更新、または出典対応の訂正がある。
When: 同じキーで再送するか、期待版を指定して新しい取込版を保存する。
Then: 同一要求は同じBrief後継版とreceiptを返し、異なるpayloadのキー再利用や古い期待Brief版は拒否される。既存Idea・Brief・Source・Claim・Evidenceは変更または削除されない。

## 質問リスト

| ID | 状態・質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| Q-1 | 利用者は過去の外部調査実施を確認済み。新しいWeb検索・Deep Research・モデル呼出しは行わない | 実装責任者 | 実装前 |
| Q-2 | 17件の引用と元回答の対応段落を既存会話内で照合済み。新しい外部アクセスなしに保存済み公開根拠へ対応付ける | 実装責任者 | 確認済み |
| Q-3 | 元の調査日時・過去のDots Campaign承認記録は不明として扱う。証拠が別途見つかった場合だけその範囲を記録する | 実装責任者 | 実装前 |

## スコープ外

- URLへの新規アクセス、追加Web検索、Deep Research、モデルによる要約生成。
- 過去のCampaign、承認、ResearchRun、監査レシート、開始・終了時刻の補造または遡及作成。
- 利用者が明示していない出典の追加、架空URL、未確認の章対応。
- 既存Idea・Brief・Source・Claim・Evidenceの上書き、削除、共有範囲の拡大。
- 過去調査取込を現行Campaignの調査許諾や現行Runとして扱うこと。

## 契約と安全境界

- 元回答から確認した公開URL・題名・公開短文は、既存の`capture_source`等の保存経路で保存する。`capture_source`はページを取得せず、確認済みの値だけを記録する。公開Source/SourceRevisionおよび公開Claim/Evidenceに限り`egress_policy=shareable`を明示し、他の本文・連絡先・会話全文は共有しない。
- ClaimとEvidenceは既存のSourceRevision/ContentChunk系譜を使う。Evidenceは保存済みChunkを参照し、URL・題名だけからEvidenceを捏造しない。短文または章対応が確認できない引用は根拠としてBriefへ載せない。
- 過去調査由来は新しい汎用ノードではなく、Briefの`origin=prior_research_import`マーカーで示す。マーカーのないBriefは従来どおりで、現行Run由来は従来の`research_run_ids`で区別する。今回の保存時刻はサーバー生成のBrief `created_at`を使い、元の調査時刻は保存・推定しない。過去会話の識別子・全文は一般検索、Home、共有投影へ出さない。
- Brief後継版は各節の本文を引き継ぎ、確認できた引用と由来metadataを保存する。既存Brief版は不変に保つ。現行Campaign/Runの`research_run_ids`や承認記録を流用・偽造せず、通常の`save_researched_idea_brief`検査を緩めない。
- Home/MCPは「過去調査由来」と現行Runによる調査済みを区別して表示する。既存の引用不足、非公開、旧版の判定は維持し、状態を単一の`researched`相当に丸めない。
- 保存要求は同一owner、現行Brief期待revision、安定したidempotency keyに結び付ける。同じpayloadの再送は同じ後継Briefとreceiptを返し、別payloadのキー再利用とstale revisionは拒否する。既存のowner、current source、URL安全検査、citation lineage、Evidence共有条件を緩めない。
- Source/Claim/Evidenceの取込は既存の個別保存契約を使い、全系譜の新しい一括transactionやrollback機構を追加しない。最終的なBrief後継版とそのreceiptだけをowner/CAS/idempotency付きで原子的に確定する。Brief保存に失敗しても既存の根拠記録は保持し、再送可能な状態とする。

## 取消・ロールバック

- Brief保存失敗時はBrief版とreceiptを確定せず、既に個別保存されたSource/Claim/Evidenceは変更・削除しない。同じ要求を再送できる。
- 保存後に引用や章対応が誤りと分かった場合、既存データは削除せず、既存Brief訂正契約でowner/CAS/idempotencyを検証した新しいBrief後継版を保存する。誤った引用を含む旧版は不変の履歴として残し、通常のHome/MCPでは最新の適格版だけを表示する。
- 過去会話来歴はowner-only metadataとし、公開投影で誤りがないことを読み取り検査する。物理削除、Campaign/Runの遡及変更、URLへのアクセスはしない。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| S-1 出典照合 | 元回答にある公開引用のURL・題名・公開短文・章対応を、外部アクセスなしで確認できるものだけ整理 | 検査: 取込可能/メタデータのみ/保留の件数だけを記録し、本文・会話ID・URL・個別題名をGitやログへ出さない。未確認項目を埋めない | 既知 |
| I-1 Brief由来契約・保存 | Briefに任意`prior_research_import` origin markerを追加し、現行公開Evidence付きBrief後継を既存保存経路で記録 | 検査: originの保存/既存payload既定値、実在の現行共有Evidence必須、Run/Campaignを作らないこと、Brief後継+receiptの原子性、再送/CAS/別payload衝突、旧版不変を単体・保存契約テストで確認 | 類推可能 |
| I-2 取得・表示 | MCPとHomeで過去調査由来metadataと8章引用を表示する | 検査: Home/MCPの引用が一致し、過去調査由来を現行Runの`researched`と誤認させない。会話来歴を返さず、private/noncurrent/秘密URLを除外する | 類推可能 |
| V-1 通し確認 | 固定fixtureで保存→再取得→Brief訂正→現行引用確認 | 検査: 新規調査・外部アクセスなしで、引用一致、最新の適格版、旧版保持、Brief保存失敗後の安全な再送を確認 | 類推可能 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| 過去調査の表現 | Briefの任意`prior_research_import` origin markerで示し、通常のBrief後継版として保存する | 新しい汎用import node/lifecycleや`research_imported`全体状態を追加する | 現行Runは既存Run参照で区別し、変更面をBrief契約に限定 |
| 保存境界 | 既存のSource/Claim/Evidence保存契約を使い、最終Brief後継+receiptのみ原子的に確定する | 全根拠とBriefを束ねる新しい一括transaction/rollback framework | 部分保存済み根拠は再利用可能とし、汎用基盤を避ける |
| 取込版 | 既存Briefを変更せず、既存CAS/idempotencyを使う新revisionへ引用と由来metadataを保存する | 既存payloadを上書き、またはRun参照だけを流用する | 履歴・CAS・再送境界を保持 |
| 出典不足 | 短い公開要約または章対応が確認できない引用をEvidence化しない | URL・題名から本文やClaimを推測して作る | 検証可能な根拠だけ保存 |
| 原時刻 | 取込日時は現在時刻、原調査日時は証拠がある場合だけ保存 | 元回答の表示日や現在時刻を調査完了時刻として代用する | 取込時刻と原調査時刻を区別 |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-09-27 | 過去調査出典の独立した取込契約を追加 | 実施済みと確認された調査を未調査と誤表示せず、存在しないCampaign/Run/時刻を遡及作成しないため | S-1、P-1、I-1、I-2、V-1 |
| 2026-09-27 | 独立import nodeと一括系譜transactionを外し、Brief由来metadataとBrief後継保存へ縮小 | 復元済み根拠の再利用に限定し、汎用取込基盤や周辺ライフサイクルの新設を避けるため | S-1、I-1、I-2、V-1 |
| 2026-09-27 | 過去調査を示す任意Brief origin markerと現行共有Evidence検査の受け入れ条件を具体化 | 保存時刻はBrief作成時刻に限定し、元調査時刻・Run・Campaignを作らないI-1境界を固定するため | I-1 |
