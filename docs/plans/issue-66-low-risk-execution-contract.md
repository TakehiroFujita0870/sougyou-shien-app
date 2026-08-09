# Issue #66 低リスク実行契約計画
最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標
週次時間、家計保護資金、small experiment、撤退条件、resource、roadmap、unit economics由来の資金前提を決定的local契約で検証する。実在金融機関・個人情報・外部送信を扱わない。

## ユーザーストーリーと受け入れ条件
### US-66-01
As a 本業や家庭の制約を持つ利用者, I want可逆な小実験を上限内で計画したい, so that生活を損なわず検証できる。
Given: 週次時間上限、家計保護上限、制約category、small experiment、撤退条件を入力する
When: local evaluatorを実行する
Then: 時間・支出が上限内で、実験が可逆なら安全候補と残余時間・残余資金を返す。
### US-66-02
As a 利用者, I want資源と資金調達候補を確認したい, so that外部申請を自動化せず次の確認を選べる。
Given: 必要resource、段階的roadmap、unit economics由来の資金前提を入力する
When: local evaluatorを実行する
Then: unit economicsの営業利益をsmall experimentへ割り当て可能な上限として検証し、self-funded experimentと公式条件確認が必要な一般カテゴリだけを返し、融資額・機関名・適格性を断定しない。

## スコープ外
- 実在銀行・公庫・補助金の推薦、融資申請、融資可能額・条件の断定。
- 銀行名、口座、残高、認証情報、家族/勤務先の個人情報、外部API、UI/App.jsx。

## タスク
| ID | 成果物 | 完了判定（検査:） | 不確実性 |
|---|---|---|---|
| T-66-01 | local execution-plan evaluator | 検査: 時間・資金・可逆性・撤退条件・resource・roadmap・一般資金カテゴリのpytest | 類推可能 |

## ADR
| 判断 | 選択と理由 | 却下案と理由 | 結果 |
|---|---|---|---|
| ADR-66-01 | 制約をemployee/childcare/caregiving/weekend_onlyのcategoryに限定し、個人詳細を保存しない | 自由記述の家族・勤務先情報はPIIを増やすため却下 | local fixtureで時間境界を検証する |
| ADR-66-02 | 資金候補はself_fundedとofficial_conditions_checkの一般カテゴリに限定する | 実在機関の推薦・融資額推定は金融助言と外部情報の境界を越えるため却下 | 条件確認が必要な注記を常に返す |
| ADR-66-03 | unit economics営業利益の正値をsmall experimentの利益上限として使い、支出超過または負値を拒否する | 未使用入力として残す案は財務前提を黙って無視するため却下 | 正/負の結果差をpytestで固定する |

## 変更履歴
| 日時 | 変更 | 理由 | 影響タスク |
|---|---|---|---|
| 2026-08-09 | 初版 | Issue #66第一sliceの低リスク実行境界を定義 | T-66-01 |
