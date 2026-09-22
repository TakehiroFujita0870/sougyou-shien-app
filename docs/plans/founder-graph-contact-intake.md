# Founder Graph contact intake 計画

最終検証日: 2026-09-22

## 要望 / ゴール / 成功指標

### 要望

ChatGPTで整理した名刺・会話の人物と組織を、private contact境界を保ったままFounder Graphへ保存する用途限定write toolを追加する。

### ゴール

Person、Organizationを個別に保存し、後続の`link_entities`で所属・能力・協力候補の関係を根拠付きで追加できる状態にする。

### 成功指標

- `capture_person`と`capture_organization`がowner-scoped、idempotent、unknown-field拒否で動作する。
- Personの連絡先とprivate notesはlocal_onlyに固定され、shareable指定を拒否する。
- Organizationは明示されたegress policyを保持し、既存read projectionへ流せる。
- capture toolは自動名寄せ、外部検索、OCR、自動関係作成を行わない。

## ユーザーストーリーと受け入れ条件

### US-CONTACT-1 人物を保存する

As a local founder, I want to store a person from a card or conversation, so that later ideas can be connected to the person without losing private contact data.

Given: a name, optional description, contact mapping, private notes, and idempotency key are supplied.
When: `capture_person` is called for the local owner.
Then: one Person node is stored with local_only egress, and replay returns the same receipt without a duplicate.

Given: a person command requests shareable egress while contact or private notes are present.
When: `capture_person` is called.
Then: the command is rejected before persistence.

### US-CONTACT-2 組織を保存する

As a local founder, I want to store an organization separately, so that people and ideas can be connected to a stable organization node.

Given: a name, description, egress policy, and idempotency key are supplied.
When: `capture_organization` is called.
Then: one Organization node is stored with the requested safe fields and owner boundary.

### US-CONTACT-3 関係は別commandにする

As a local founder, I want contact capture to avoid guessing relationships, so that a name card does not become an unsupported fact.

Given: a Person and Organization were captured.
When: a relationship is desired.
Then: the caller must use `link_entities` with relation, status, evidence, confidence, and expiry; capture itself creates no relationship.

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| Q-CONTACT-01 | 名刺画像の手入力、CSV、ローカルOCRの初期範囲 | 利用者兼製品責任者 | SP-FG-06の比較後 |

## スコープ外

- 名刺画像OCR、CSV parser、連絡先アプリ同期、メール送信。
- LLMによる自動名寄せ、重複merge、所属推定、関係自動作成。
- 外部Web検索、人名のpublic profile enrichment。
- 物理削除、複数利用者、公開MCP endpoint。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| CONTACT-1 | `capture_person` / `capture_organization` write tool | 検査: local-only contact、shareable拒否、organization projection、replay、unknown field、owner mismatchをfocused pytestで確認する | 類推可能 |
| CONTACT-2 | tool schema / docs / regression | 検査: MCP tool定義、全backend tests、`py_compile`、`git diff --check`を確認する | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| ADR-CONTACT-1 separate capture | PersonとOrganizationを別commandで保存し、関係は`link_entities`へ分離する。名刺の不確実な所属や協力関係を事実化しない | capture時にorganization linkまで自動作成する案は根拠・確信度・期限を欠くため却下 | US-CONTACT-3のproposed / inferred契約を維持できる |
| ADR-CONTACT-2 private default | Personのcontact/private_notesがある場合はlocal_onlyを強制する | 便利さを理由にshareableへ自動降格する案は外部送信境界を曖昧にするため却下 | MCP readでprivate fieldを返さない既存契約と整合する |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-09-22 | 初版。Person / Organization captureとprivate境界を定義 | 人的ネットワークをFounder Graphへ取り込む最小write sliceとするため | CONTACT-1〜CONTACT-2 |
| 2026-09-22 | `capture_person` / `capture_organization`、冪等性、owner境界、unknown-field拒否を実装 | 通常チャットから人物・組織を安全に取り込む最小write surfaceを追加するため | CONTACT-1〜CONTACT-2 |

## 実装メモ

- 計画タスク: CONTACT-1 / CONTACT-2
- 受け入れ条件: US-CONTACT-1〜US-CONTACT-3
- 実装: `McpWriteSurface`へ8番目までの用途限定toolとして`capture_person`と`capture_organization`を追加した。
- Personはこのcommand経由では`local_only`に固定し、contact/private notesをshareableまたはexplicitへ出さない。Organizationは`egress_policy`を保持し、既存projectionへ渡せる。
- captureはPersonとOrganizationを個別に保存し、関係を自動作成しない。関係は根拠付きの`link_entities`で明示する。
- 入力はunknown fieldを拒否し、idempotency keyを`InMemoryGraphWriteService`へ渡す。再送はreplay、異なるpayloadはconflictとなる。
- 自動名寄せ、OCR、外部検索、所属推定、UIはこのsliceに含めない。
- 追加テスト: `backend/tests/test_founder_graph_mcp_write.py`の8 tool定義、Person / Organization capture replay、local-only拒否、unknown field、owner mismatch。
- 検査結果: `uv run --isolated --python 3.14 pytest backend/tests/test_founder_graph_mcp_write.py backend/tests/test_founder_graph_mcp_api.py -q` は24 passed、`uv run --isolated --python 3.14 pytest backend/tests -q` は254 passed / 16 skipped、`py_compile` と `git diff --check` はpass（FastAPI / Starletteの既存deprecated warning 5件）。
