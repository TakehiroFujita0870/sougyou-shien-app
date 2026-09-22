# Founder Graph Phase 6 接続前契約監査

最終検証日: 2026-09-22

## 要望 / ゴール / 成功指標

要望: T-FG-21、T-FG-22、T-FG-23について、外部のChatGPT、Deep Research、資格情報を使わずに完了できる契約と、実機接続がなければ証明できない事項を区別する。

ゴール: ローカルのread、preflight、write、private投影の既存契約をPhase 6の各受け入れ条件へ対応付け、未接続の環境で完了を誤認しない接続試験の証跡を固定する。

成功指標: この監査で各T-FG項目について「ローカル契約」「実機必須の証跡」「完了判定」が一意に読め、外部接続なしに実機完了と主張する項目が0件である。

## ユーザーストーリーと受け入れ条件

### US-P6-01 許諾前の境界を確認する

As a 単独利用者, I want アイデア検知から調査許諾までのローカル処理を接続前に検証したい, so that 外部調査を意図せず開始しない。

Given: `capture_idea`、`GraphReadPort`、`ResearchBrief`が合成データで利用可能である。

When: Phase 6の代表会話をChatGPT未接続環境で評価する。

Then: 保存、全体検索、shareable preflightの契約だけを確認済みとし、検知、許諾表示、外部調査0件は実機接続の証跡がない限り未完了と記録する。

### US-P6-02 調査結果の履歴を守る

As a 単独利用者, I want 複数Runと追調査の保存境界を接続前に確認したい, so that 実機handoffの結果で旧レポートを上書きしない。

Given: Campaign、Run、ReportVersionの不変契約と用途限定write toolが合成データで利用可能である。

When: 1回、2回、追加質問の各経路を接続前に評価する。

Then: 保存側の参照整合性と冪等性だけを確認済みとし、Deep Research通知からのhandoffは実機試験まで未完了と記録する。

### US-P6-03 private egressを実機前に縮退させる

As a 単独利用者, I want 非公開連絡先とhidden contextが外部queryへ渡らない前提を確認したい, so that 実接続前に漏えいする設計を残さない。

Given: shareable projection、ResearchBrief、read MCPのprivate除外テストが通っている。

When: 悪性Web文字列を含む合成資料をread/preflight境界へ渡す。

Then: 文字列をuntrusted dataとして扱いprivate fieldをbriefへ出さないことだけを確認済みとし、ChatGPTが組み立てる外部queryの実送信内容は実機captureがない限り未完了と記録する。

## 監査結果

| 予定 | ローカルで確認済みの証跡 | 実機必須の証跡 | 現在の判定 |
| --- | --- | --- | --- |
| T-FG-21 | `test_founder_graph_mcp_write.py`の`capture_idea`冪等性、`test_founder_graph_research_brief.py`の三領域preflightとprivate除外 | ChatGPT developer-modeの代表会話5件で、検知、保存、search/fetch、許諾提示、Deep Research未開始を同一時系列で記録 | 部分実装。ChatGPT検知と許諾画面は未検査 |
| T-FG-22 | `test_founder_graph_mcp_write.py`の二Run、Campaign scope、ReportVersion参照、再送境界 | Deep Researchの1回、2回、追加質問を実行し、ChatGPT通知後のwrite-back、別input snapshot、新ReportVersion、旧版不変を記録 | 部分実装。通知とhandoffは未検査 |
| T-FG-23 | `test_founder_graph_research_brief.py`、`test_founder_graph_threat_model.py`のshareable allowlist、private field、prompt injection、owner境界 | 悪性Web fixtureを含む実機Deep Researchの外部query、MCP request、write-back payloadをcaptureし、private field、contact、hidden contextが0件であることを照合 | 部分実装。外部query実送信は未検査 |

## 接続試験の最小証跡

実機試験は、実データを使わず合成fixtureを使う。資格情報の値、トンネル識別子、個人連絡先、会話原文を試験記録へ残さない。

| ID | 経路 | 必須観測 | 合格条件 |
| --- | --- | --- | --- |
| P6-E1 | T-FG-21の代表会話5件 | 会話ID、MCP tool名、idempotency keyのhash、保存ID、search/fetch結果数、許諾提示、外部調査開始の有無 | 各会話で保存とpreflightが記録され、外部調査開始が0件 |
| P6-E2 | T-FG-22の1回調査 | Campaign ID、Run ID、ReportVersion ID、通知時刻、write receipt | 許諾済みCampaignへ一つのRunと一つのReportVersionが保存される |
| P6-E3 | T-FG-22の2回調査 | Campaign ID、二つのRun ID、二つのinput snapshot hash、比較ReportVersion ID、親ReportVersion ID | Runとinput snapshotが異なり、旧Runと旧ReportVersionのrevisionが変化しない |
| P6-E4 | T-FG-22の追加質問 | 追加質問の分類、Run追加またはReportVersion追加、change reason | 外部調査時だけ新Run、再構成時だけ新ReportVersionが作られる |
| P6-E5 | T-FG-23の悪性Web fixture | 外部query、MCP request、ResearchBrief、write-back payloadのredacted capture | `contact`、`private_notes`、`source_text`、hidden contextが全captureで0件 |

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| Q-P6-01 | ChatGPTが許諾前のrepresentative conversationで、MCP writeを呼ぶときのplatform confirmation表示を記録できるか | 技術責任者 | SP-FG-01の実機開始時 |
| Q-P6-02 | Deep Researchの外部queryとtool payloadを、資格情報や会話原文を露出せずにcaptureできるか | 技術責任者 | SP-FG-02の実機開始時 |

## スコープ外

- Secure MCP Tunnel、ChatGPT developer-mode、Deep Researchの実接続。
- OpenAI API key、runtime credential、実ユーザーデータ、外部Webへの送信。
- ChatGPTの検知器、許諾UI、通知UIの実装または変更。
- 既存のdomain、MCP、Neo4j、FastAPI、UIコードの変更。
- 実機試験で得た会話、外部query、資格情報の永続保存。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| P6-AUD-01 | Phase 6のローカル契約と実機証跡の対応表 | 検査: `rg -n "T-FG-21|T-FG-22|T-FG-23|P6-E1|P6-E5" docs/plans/founder-graph-phase-6-contract-audit.md` が各1件以上 | 既知 |
| P6-AUD-02 | 実接続で収集する最小redacted evidence contract | 検査: `rg -n "contact|private_notes|source_text|hidden context|0件" docs/plans/founder-graph-phase-6-contract-audit.md` が各1件以上 | 類推可能 |
| SP-P6-01 | T-FG-21の代表会話5件をdeveloper-mode MCPで実機実行 | 検査: P6-E1の5記録を実接続時に照合する | 未知・先行スパイク |
| SP-P6-02 | Deep Researchから通常chat write-backまでの実機handoffを実行 | 検査: P6-E2、P6-E3、P6-E4を実接続時に照合する | 未知・先行スパイク |
| SP-P6-03 | 悪性Web fixtureを使うegress実機試験 | 検査: P6-E5の全captureでprivate fieldが0件であることを照合する | 未知・先行スパイク |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| P6-ADR-01: 完了の表現 | ローカルcontractとChatGPT実機接続を別証跡にする。外部側の会話制御はDots単体のpytestで証明できない | local test成功をPhase 6完了と扱う。未検証の通知、許諾、外部queryを隠すため却下 | T-FG-21から23は実機evidenceまで部分実装とする |
| P6-ADR-02: egress試験 | 実機captureは合成fixtureとredacted metadataを使い、private fieldの出現数を照合する | 実ユーザー会話または連絡先で試験する。不要な個人情報送信と記録を増やすため却下 | Gate Cの根拠を再現可能な最小記録にする |
| P6-ADR-03: ChatGPT責務 | 検知、許諾表示、Deep Research、通知はChatGPT側の観測対象とし、DotsはMCP read/writeと安全投影だけを検証する | Dotsが独自の検知器または通知基盤を追加する。確定した責務境界を崩すため却下 | 接続試験の失敗をDotsのdomain変更で隠さない |

## 実装メモ

- 計画タスク: P6-AUD-01, P6-AUD-02
- 受け入れ条件: US-P6-01, US-P6-02, US-P6-03
- 追加テスト: なし。既存のread、ResearchBrief、write、threat-model fixtureを監査対象にした文書限定sliceである。
- エラー分類: 外部接続未実施は失敗ではなく未検査。実機の失敗はP6-E1からP6-E5の該当証跡とともに記録する。
- API互換性: 影響なし。
- 検査結果: `rg`による監査項目確認と`git diff --check`を実行する。
- 未検査境界: ChatGPT tool discovery、platform confirmation、Deep Research通知、外部query、実機write-back、悪性fixtureの実送信。

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-09-22 | 初版の接続前契約監査を追加 | 外部資格情報なしに確認可能な契約と実機必須の証跡を分離するため | P6-AUD-01、P6-AUD-02、SP-P6-01から03 |
