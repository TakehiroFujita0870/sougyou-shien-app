# Claim共有指定の移植計画
最終検証日: 2026-09-26

## 要望 / ゴール / 成功指標
要望: APIとstdioの双方で、本人が明示したClaimだけをshareableにできる。
ゴール: `append_claim`に閉じた任意のegress policyを追加し、省略時はlocal-onlyを保つ。
成功指標: 専用テストで既定非公開、明示公開、同じ冪等キーでの公開昇格拒否、無効値/他owner拒否、APIとstdioのschema一致を確認する。

## ユーザーストーリーと受け入れ条件
### US-1
As a local owner, I want to explicitly mark a Claim shareable, so that only Claims I approve can appear through MCP reads.
Given: `append_claim`の入力にegress policyがない。
When: Claimを保存してMCPから取得する。
Then: Claimのegress policyはlocal-onlyであり、読み取り結果に表示されない。

### US-2
As a local owner, I want to opt in a Claim to sharing, so that approved Claims are reusable through the existing MCP projection.
Given: Claimの入力でegress policyにshareableを指定する。
When: Claimを保存して既存の読み取り経路で取得する。
Then: Claimは既存のread allowlistだけで投影され、Source/Evidenceの共有規則は変わらない。

## 質問リスト
| ID | 質問 | 決定者 | 期限 |
|---|---|---|---|
| なし | 要求された契約は確定済み | — | — |

## スコープ外
- Claim以外のegress policyやMCP read allowlistの変更。
- `research_allowed`、`confidential`、`explicit`を含むlocal-only/shareable以外の値。
- 外部検索、LLM、DB/service操作、データ移行、metadata fingerprintの変更。
- live作業ツリーにある他機能の移植。

## タスク
| ID | 成果物 | 完了判定（検査:） | 不確実性 |
|---|---|---|---|
| T-1 | 失敗する専用テスト: default/private, shareable, no-upgrade, invalid/owner, API/stdio parity | `uv run pytest backend/tests/test_founder_graph_mcp_claim_sharing.py -q` | 既知 |
| T-2 | schema enumとClaim生成handlerを更新 | T-1および`uv run pytest backend/tests/test_founder_graph_mcp_claim_sharing.py backend/tests/test_founder_graph_mcp_write.py backend/tests/test_founder_graph_mcp_api.py backend/tests/test_founder_graph_mcp_stdio.py -q` | 既知 |

## ADR
| 判断 | 選択と理由 | 却下案と理由 | 結果 |
|---|---|---|---|
| Claim egress | Optional `local_only`/`shareable` enum、default `local_only`; matches Claim domain and preserves existing callers | Default shareable weakens privacy; additional modes have no approved contract | Only explicit shareable enters the unchanged public projection |
| Schema snapshots | Do not copy a fingerprint from the broader live worktree | It would encode unrelated tool/catalog changes absent from this baseline | Assert API and stdio expose the same append_claim input schema |

## 変更履歴
| 日時 | 変更 | 理由 | 影響タスク |
|---|---|---|---|
| 2026-09-26 | 初版 | main基点に限定したClaim共有の移植契約 | T-1,T-2 |
