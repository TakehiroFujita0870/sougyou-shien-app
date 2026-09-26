# Research済みIdeaBriefの純粋検証 配送計画
最終検証日: 2026-09-26

## 要望 / ゴール / 成功指標
要望: 既存IdeaBriefVersionを、本人のIdeaと現行許諾に紐づく完了ResearchRunだけで保存時にResearch済みbriefとして受け入れる純粋validatorを追加する。
ゴール: 不完全な8章、所有者/Idea違い、未完了・未認可・期限外・時刻不整合のRunを拒否し、検証関数からRun本文を出さない。
成功指標: 固定時計の合成ドメインfixtureで許可/拒否条件を再現し、validatorが成功時に`None`を返しraw Run内容を戻さないことを確認する。

## ユーザーストーリーと受け入れ条件
### US-RB-01
As a local owner, I want a researched brief validated against my exact Idea and its completed research, so that unverified drafts cannot be treated as researched.
Given: 保存しようとする8つの非空章、owner一致の対象Idea、登録済みのResearchRun参照がある。
When: 保存時のtrusted current campaign historyと受入時刻で検証する。
Then: 各Runが同じowner/Ideaに属し、COMPLETEDかつ現在の認可snapshot/revisionに一致し、Run開始/終了が承認・expiry・現在時刻の範囲内なら`None`を返す。

### US-RB-02
As a local owner, I want stale, incomplete, or unrelated research rejected without returning raw Run data, so that the pure gate does not leak research payloads or accept stale authorization.
Given: 空章、別owner/Idea、Run欠落/重複/未完了、旧snapshot、bool/非整数revision、無効Campaign状態、期限切れ、時刻欠落/逆転/未来のいずれかがある。
When: 同じvalidatorを呼ぶ。
Then: `ResearchedBriefValidationError`だけを送出し、例外メッセージへRun本文/入力/結果/証拠を含めない。

## 質問リスト
| ID | 質問 | 決定者 | 期限 |
|---|---|---|---|
| なし | domain入力と認可契約はmainに存在し、今回の範囲は純粋validatorに限定する | — | — |

## スコープ外
- IdeaBrief、ResearchCampaign、ResearchRunモデル自体の変更。
- 永続化store/adapter、Neo4j query/transaction、MCP/API/stdio/runtime接続。
- 外部調査、run作成、報告生成、証拠本文投影。
- Campaign/Runをstorageから解決する権限境界の実装。このvalidatorの引数は信頼済みcurrent registry/read結果から組み立てる。
- 保存済みBriefを後日の閲覧時に再判定すること。認可期限経過後も既に受け入れたBriefは消えず、将来の保存層はaccepted時刻/provenanceを保持し、読み取りで現在時刻を代入して再検証しない。

## タスク
| ID | 成果物 | 完了判定（検査:） | 不確実性 |
|---|---|---|---|
| T-RB-01 | 受け入れ条件のfocusedテスト | 検査: `uv run pytest backend/tests/test_founder_graph_researched_brief.py -q` | 既知 |
| T-RB-02 | Pure validation functionと安全なエラー型 | 検査: focusedテストおよび`uv run pytest backend/tests -q` | 既知 |

## ADR
| 判断 | 選択と理由 | 却下案と理由 | 結果 |
|---|---|---|---|
| 入力境界 | IdeaBriefVersion、対象Idea、Run値のsequence、CampaignAuthorizationRegistryを受け取り、既存`validate_run_campaign_reference`を再利用する | Store/Neo4j/MCPを新設moduleへ取り込むと副作用と認可境界が混ざる | 呼出側は保存時にregistryとRun値を信頼済みsourceから渡す。永続化側の権威的loadは別packetで実装する |
| Run時刻 | `at`を任意注入し、省略時だけUTC現在時刻を使う。開始>=承認、終了>=開始、終了<=at、Run終了<認可expiryを検査する | global clockのpatchや実時刻固定は再現性を損なう | 成功・境界拒否を副作用なしで決定的に検証する |
| 結果 | 保存時gateとして成功時は`None`、拒否時は固定メッセージの`ResearchedBriefValidationError`のみ | 生Runやその内容を成功値/例外へ返すと情報を漏らし得る | Runは入力検証にだけ使い、結果から切り離す。歴史的閲覧での再判定はしない |

## 変更履歴
| 日時 | 変更 | 理由 | 影響タスク |
|---|---|---|---|
| 2026-09-26 | 初版 | IdeaBrief ResearchRun参照をResearch済みの純粋gateへ接続する | T-RB-01,T-RB-02 |
| 2026-09-26 | revision型境界を明記 | boolはPython上intの派生型であるためRun authorization_revisionの完全一致確認を明示する | US-RB-02,T-RB-01,T-RB-02 |
| 2026-09-26 | 保存時gate境界を明記 | Campaign expiry後も既存accepted briefをread時に無効化しない | US-RB-01,T-RB-02 |
