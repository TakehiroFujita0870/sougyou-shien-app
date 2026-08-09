# 管理者 demo session/virtual data adapter 計画

最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標
要望: 管理者用 demo principal と仮想データを production auth/user data から分離する。
ゴール: 明示的 demo session、owner/space 境界、reset、共通 fixture source を UI なしで提供する。
成功指標: demo 限定で再現可能な fixture を取得でき、通常 principal は取得不可、PII/secret は含まれない。

## ユーザーストーリーと受け入れ条件
### US-DEMO-1
As an administrator, I want an explicit demo session, so that virtual data never looks like production data.
Given: demo adapter を生成する。
When: session を開始する。
Then: demo principal と demo owner/space が返り、production auth は変更されない。
### US-DEMO-2
As a test surface, I want a resettable fixture source, so that Home/Project/Knowledge can share deterministic data.
Given: demo session が有効である。
When: fixture を取得し reset する。
Then: 同一 owner/space の fixture が再現され、reset 後は初期状態に戻る。

## スコープ外
- production auth/user data、外部接続、PII/secret、UI/App/Shell/style、upload/API。

## タスク
| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-DEMO-1 | demo principal/session と fixture adapter | 検査: adapter 契約テスト | 既知 |

## ADR
| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| demo boundary | 固定 id の demo principal と demo owner/space を adapter 内に閉じ込める。 | local auth の既存 principal を流用すると production 誤表示を検出できない。 | 採用 |
| reset | fixture source は immutable seed の clone を返し reset する。 | global singleton はテスト間の漏洩を招く。 | 採用 |

## 変更履歴
| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | 初版 | demo 基盤境界を固定 | T-DEMO-1 |
