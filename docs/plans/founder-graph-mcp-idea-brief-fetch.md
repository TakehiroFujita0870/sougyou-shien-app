# ChatGPT向け IdeaBrief 読み取り 計画
最終検証日: 2026-09-27

## 要望 / ゴール / 成功指標
要望: 意味抽出に入る前に、ChatGPTが所有者の最新・現行IdeaBriefを読み取れる入口を追加する。
ゴール: MCPのread-only toolから、共有許可済みの現行Ideaに結び付く最新Briefの8章本文と共有可能かつ現行のEvidence IDだけを返す。
成功指標: 別所有者、旧Idea、未共有Brief/Idea、未知IDを安全に隠し、owner decision・Run情報・原文・locator・非共有/非現行Evidenceを返さないことをAPI、stdio、tool catalogで検査する。

## ユーザーストーリーと受け入れ条件
### US-RP04-BRIEF-READ
As the local owner using ChatGPT for semantic extraction, I want ChatGPT to fetch my latest shareable brief for the current Idea, so that extraction uses the approved current summary and safe evidence references.
Given: owner-scoped current shareable Ideaと、同じIdeaに基づくlatest shareable IdeaBriefがあり、8 section valuesを持つ。
When: owner-bound MCP clientが`fetch_idea_brief`へIdea IDを渡す。
Then: 結果にBrief ID、Idea ID、および8章のindex/title/content/shareable-current evidence IDsだけが含まれる。
Given: IDが未知、別所有者、旧Idea、未共有Idea/Brief、または最新Briefがない。
When: MCP clientが`fetch_idea_brief`を呼ぶ。
Then: `not_found`になり、秘密の有無や他所有者記録を区別しない。
Given: sectionに非共有、inactive、旧Source revisionまたは不整合lineageのEvidence IDがある。
When: 最新Briefが返される。
Then: そのEvidence IDだけがsectionから除かれ、owner decisions、Run input/result、Source本文、locatorは結果に存在しない。

## 質問リスト
| ID | 質問 | 決定者 | 期限 |
|---|---|---|---|
| なし | tool入力は現行Idea IDのみ、返却は最新共有Briefの8章に限定する既存受入契約で確定 | — | — |

## スコープ外
- Briefの作成・改訂・削除、検索一覧、履歴取得。
- Briefのowner decision、facts、inferences、unconfirmed、ResearchRunの内容。
- 共有範囲の変更、調査開始、意味抽出/関係保存の実行。
- 共有RP-SP-04 fixtureおよび既存fixtureファイルの変更。

## タスク
| ID | 成果物 | 完了判定（検査:） | 不確実性 |
|---|---|---|---|
| T-RP04-BRIEF-01 | owner-bound read adapterと閉じた`fetch_idea_brief` projection | `uv run pytest backend/tests/test_founder_graph_mcp.py backend/tests/test_founder_graph_mcp_api.py backend/tests/test_founder_graph_mcp_stdio.py -q`で最新/現行、Evidence allowlist、privacy、owner missを確認 | 類推可能 |
| T-RP04-BRIEF-02 | catalog/API/stdio parityと負例テスト | 前記focused suite、`uv run pytest backend/tests -q`、`git diff --check`を実行 | 既知 |

## ADR
| 判断 | 選択と理由 | 却下案と理由 | 結果 |
|---|---|---|---|
| lookup key | 現行Idea IDだけを入力にし、owner-bound read adapterでcurrent Idea lineageとlatest Briefを解決する | Brief IDを直接受け取ると旧Briefを選択でき、current-only条件を破る | 別所有者・旧Idea・Brief非共有は同じnot-found projectionとする |
| projection | 8 sectionのindex/title/content/evidence IDsだけ返し、Evidenceはactive/shareableかつ現行source lineageを検証する | dataclass全体や既存NodeViewを返すとowner decision、Run参照、原文、locator等が混入する | 新規read-only MCP toolを共通catalog/API/stdio経路へ追加する |

## 変更履歴
| 日時 | 変更 | 理由 | 影響タスク |
|---|---|---|---|
| 2026-09-27 | 初版 | RP-04 semantic extraction前に安全なBrief read入口を用意する | T-RP04-BRIEF-01,T-RP04-BRIEF-02 |
