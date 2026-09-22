# Founder Graph 脅威モデル・オフライン検証計画

最終検証日: 2026-09-22

## 要望 / ゴール / 成功指標

要望: Founder Graph の読み取り境界について、プロンプトインジェクション、private egress、owner 境界、ローカルDB停止を攻撃ケースとして固定し、既存の投影契約に対するオフライン回帰検査を追加する。

ゴール: Dots の read-only MCP 境界が、信頼されないグラフ内容を命令として実行せず、shareable でない値と別 owner の値を返さず、グラフ停止時に安全な unavailable エラーへ縮退することを、外部接続なしで検証可能にする。

成功指標: `backend/tests/test_founder_graph_threat_model.py` が上記4攻撃ケース、静的shareable allowlist、read-only surfaceを検証し、focused pytest と `git diff --check` が成功する。

## 信頼境界と保護対象

| 境界 | 入力または依存 | 保護対象 | fail-closed 動作 |
| --- | --- | --- | --- |
| グラフ内容 → MCP read projection | 会話、Web、ファイルから取り込んだ文字列 | Dots の制御フローと tool surface | 文字列は `untrusted_text` として返すだけで、tool名・命令として解釈しない |
| local graph view → shareable projection | Person、Campaign、InstructionArtifact を含む local view | contact、private_notes、path、scope、owner情報 | `SHAREABLE_PROJECTION_ALLOWLIST` にないキーを投影しない |
| read service → owner-scoped surface | `owner_id` と検索・取得結果 | 別 owner のノード、関係、識別子 | owner不一致を空結果または not_found にする |
| local DB driver → MCP surface | Neo4jまたはin-memory read port | 停止時の内部詳細と部分結果 | `unavailable` と利用者向け固定メッセージだけを返す |

## ユーザーストーリーと受け入れ条件

### US-1: 信頼されない文字列をデータとして扱う

As a founder, I want imported text to remain data at the MCP boundary, so that quoted instructions cannot invoke Dots tools.

Given: shareable な ResearchMaterial の `content` に tool 呼び出しを促す文字列がある。

When: read-only MCP の `fetch` を呼ぶ。

Then: 文字列は `untrusted_text` と `text` の値として返り、read surface の tool 定義は `search` と `fetch` の2つだけで、書き込み tool は実行されない。

### US-2: private 値と非公開 endpoint を外へ出さない

As a founder, I want local-only people and private fields excluded from shareable reads, so that an external research context cannot receive personal contact data.

Given: `PersonAsset` に contact と private_notes があり、同 owner の shareable Idea へ関係がある。

When: MCP の `search` が関係経由で Idea を見つける。

Then: Person の識別子、contact、private_notes は結果に含まれず、関係 path も local-only endpoint を含む場合は省略される。

### US-3: owner 境界を read service 全体で守る

As a founder, I want every graph read scoped to the active owner, so that a different owner cannot enumerate or fetch my nodes.

Given: graph service の owner が `owner-a` で、ノードも `owner-a` に属する。

When: `owner-b` で search または fetch を行う。

Then: search は空ページを返し、fetch は not_found になり、ノードのタイトル・ID・関係情報は返らない。

### US-4: DB停止時に内部状態を開示しない

As a founder, I want the read surface to stop safely when the local graph is unavailable, so that callers can retry without receiving driver details.

Given: read port が `GraphReadUnavailableError` を発生させる。

When: MCP の search を呼ぶ。

Then: code が `unavailable` で固定され、利用者向けメッセージに driver の内部詳細や部分結果が含まれない。

## 攻撃ケースと期待結果

| ID | 攻撃者の能力 | 攻撃入力 | 期待する拒否または縮退 | 検証 |
| --- | --- | --- | --- | --- |
| TM-1 | 外部資料または会話へ命令文を埋め込める | `Ignore previous instructions ...` を含む content | data-only の `untrusted_text` として返し、read-only tool以外を持たない | `test_prompt_injection_is_data_only_at_read_boundary` |
| TM-2 | local-only Person と shareable Idea の関係を作れる | contact、private_notes、local-only endpoint | static allowlist と relation path 再検証で除外 | `test_private_egress_and_relation_path_fail_closed` |
| TM-3 | owner_id を任意に指定できる | 別 owner の search / fetch | 空ページまたは not_found。別 owner のIDとフィールドを出さない | `test_owner_boundary_rejects_cross_owner_reads` |
| TM-4 | DB driver を停止または切断できる | `GraphReadUnavailableError` と内部詳細 | `unavailable`、固定メッセージ、内部詳細なし | `test_db_stop_returns_sanitized_unavailable_error` |
| TM-5 | 将来のnode fieldをlocal viewへ追加できる | allowlistにない private/control field | static shareable allowlistから自動的に除外 | `test_shareable_allowlist_has_no_private_control_fields` |

## スコープ外

- ChatGPT Secure MCP Tunnel の実接続、Deep Research の実ジョブ、外部サイトの認証・アクセス制御。
- Neo4j Docker実機の停止試験、backup/restore、OSプロセス権限、ネットワークファイアウォール。
- prompt injection の自然言語分類器、LLMによる自動修復、Dotsからの外部通知。
- write surface、OCR、名寄せ、embedding、レポート生成の仕様変更。
- 新しい本番ランタイム、秘密情報、実ユーザーデータの導入。

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| Q-TM-1 | なし。実外部接続の攻撃試験は別の接続ゲートで扱う。 | — | — |

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-FG-29-1 | 本文書に trust boundary、攻撃ケース、fail-closed 方針を記録 | 検査: `rg -n "TM-1|TM-2|TM-3|TM-4|TM-5|スコープ外|ADR" docs/plans/founder-graph-threat-model.md` が各1件以上 | 既知 |
| T-FG-29-2 | `backend/tests/test_founder_graph_threat_model.py` に投影、owner、停止、prompt injection の回帰fixtureを追加 | 検査: `uv run --isolated --python 3.14 pytest backend/tests/test_founder_graph_threat_model.py -q` が成功 | 既知 |
| T-FG-29-3 | 変更範囲の静的検査を実行 | 検査: `python -m py_compile backend/tests/test_founder_graph_threat_model.py` と `git diff --check` が成功 | 類推可能 |
| T-FG-29-4 | 実装メモと既知の未検査境界を更新 | 検査: 本文書の `## 実装メモ` に focused pytest 結果と scope-out がある | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| TM-ADR-1: 検証場所 | 既存の domain/MCP contract を直接呼ぶ pytest fixture。実DBや外部通信を使わず、回帰時に再現性を保つ | Neo4j実機だけの手動検証。停止・外部接続が必要で、projection contractの静的回帰にならない | オフライン契約検証を先行し、実機は別ゲートに残す |
| TM-ADR-2: projection の拒否方式 | denylistではなく `SHAREABLE_PROJECTION_ALLOWLIST` の静的集合を検査 | 新フィールドを自動的に通す広いlocal view。追加フィールド時のprivate漏えいを防げない | unknown/private field は投影から落ちる |
| TM-ADR-3: prompt injection の責務 | Dotsは命令実行をせず、文字列を untrusted data として境界付ける | Dots内で自然言語の安全判定や削除を行う。誤判定と価値層の混在を招く | orchestration側の実接続脅威は別計画へ分離 |
| TM-ADR-4: 停止時の応答 | `unavailable` と固定利用者メッセージへ変換し、driver詳細を隠す | 例外文字列をそのまま返す。環境情報や接続詳細の漏えいになる | 再試行可能な fail-closed read になる |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-09-22 | T-FG-29 の初版計画を作成 | read projectionの4境界をオフラインで固定するため | T-FG-29-1〜4 |
| 2026-09-22 | 5件のオフライン脅威回帰fixtureを追加 | prompt injection、private egress、owner境界、停止時エラー、allowlistを実装契約へ固定するため | T-FG-29-2〜4 |

## 実装メモ

- 計画タスク: T-FG-29-1〜4
- 受け入れ条件: US-1〜US-4、TM-1〜TM-5
- 追加テスト: `backend/tests/test_founder_graph_threat_model.py`
- エラー分類: 回復可能な `unavailable`、`not_found`、空ページ。内部例外詳細は利用者へ返さない
- API互換性: 影響なし。テストと文書だけの変更
- ループ周回数: 1
- 検査結果: `uv run --isolated --python 3.14 pytest backend/tests/test_founder_graph_threat_model.py -q` → 5 passed; `python -m py_compile backend/tests/test_founder_graph_threat_model.py` → 成功; `git diff --check` → 成功
- 未検査境界: 実Neo4j停止、Secure MCP Tunnel、ChatGPT Deep Research実ジョブはスコープ外
