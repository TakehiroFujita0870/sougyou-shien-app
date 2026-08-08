# Issue #30 ローカル相似アーキテクチャ第一スライス 計画
最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標
要望: 外部資格情報なしで、local/test/production の同一契約と代表的な失敗状態を検証できるようにする。
ゴール: FastAPI が設定プロファイルと各外部サービスの接続状態を返し、local/test では決定的 fake による認証・権限・上限・タイムアウト・削除を再現する。
成功指標: backend の契約テストが外部ネットワークや資格情報なしで通り、production は未接続状態を返す。

## ユーザーストーリーと受け入れ条件
### US-30-1
As a 開発者, I want 設定プロファイルごとに同じサービス名と接続状態を取得する, so that フロントエンドが接続先固有の分岐を持たない。
Given: `KADODE_RUNTIME_PROFILE=local` でAPIを作成する。
When: `GET /v1/runtime/status` を呼ぶ。
Then: Auth、DB、Storage、AI、Web Search、Billing の全サービスが `fake` 接続状態で返る。

### US-30-2
As a 開発者, I want fake Auth とサービス境界で代表失敗を起こす, so that 外部接続前にクライアント契約を検証できる。
Given: local fake の認証済み利用者と別利用者がある。
When: 別利用者の保存物を読む、または日次上限超過とタイムアウトを要求する。
Then: APIは `code` と利用者向け `message` を持つ一貫したエラー形式で403、429、504を返す。

### US-30-3
As a 利用者, I want 保存物を削除する, so that local/test で削除済み状態を確認できる。
Given: local fake に本人の保存物がある。
When: `DELETE /v1/runtime/objects/{object_id}` を本人として呼ぶ。
Then: 200と `deleted` 状態を返し、以後の取得は404となる。

### US-30-4
As a リリース担当, I want production 未設定を接続状態として取得する, so that 未実装と誤認せず安全にUIを制御できる。
Given: `KADODE_RUNTIME_PROFILE=production` で資格情報を設定しない。
When: `GET /v1/runtime/status` を呼ぶ。
Then: 全サービスが `unconfigured` と `external connection is not configured` を返す。

## 質問リスト
| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| Q-30-1 | production adapterの実ベンダーと認証方式 | CEO | 実接続を開始する前 |
| Q-30-2 | UIの接続状態表示の配置と文言 | プロダクト担当 | UI接続PR前 |

## スコープ外
- production adapterの実接続、APIキー保存、実アカウント作成、課金開始、外部公開。
- App.jsxの変更と接続状態表示の画面実装。
- 既存Supabase migrationの変更とデータ移行。

## タスク
| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-30-1 | port名・設定プロファイル・fake runtime | 検査: `uv run pytest backend/tests/test_runtime_parity.py` が通る | 既知 |
| T-30-2 | runtime状態と代表操作のFastAPI契約 | 検査: `uv run pytest backend/tests/test_runtime_parity.py` が通る | 類推可能 |
| T-30-3 | 第一スライスの利用方法と将来差し替え方針 | 検査: `rg -n "US-30-|スコープ外|ADR" docs/plans/local-parity-first-slice.md` | 既知 |
| S-30-1 | production実adapter候補を公式資料で比較するスパイク | 検査: 比較結果と結論をADRへ記録する | 既知 |
| T-30-4 | production実adapter選定 | 検査: スパイク結論を承認済みADRと照合する | 未知 |
| T-30-5 | UI接続状態コンポーネント | 検査: Storybookとコンポーネントテスト | 類推可能 |

## ADR
| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| ADR-30-1: 設定 | 環境変数で `local`、`test`、`production` を選び、APIはprofileを返す。テストとローカル起動が同じ境界を使う。 | `.env`に資格情報を置く案は未承認の認証情報管理を誘発するため却下。 | T-30-1 |
| ADR-30-2: port/adapter | サービス名を固定したProtocolと決定的fakeを置く。productionは実adapterでなくunconfigured adapterとする。 | production向けの仮ネットワークclientは誤接続の危険があり却下。 | T-30-1, T-30-2 |
| ADR-30-3: エラー | `{code, message}` をHTTP error detailに統一し、秘密情報と内部例外を返さない。 | HTTP文字列だけを返す案はUI分岐を安定化できないため却下。 | T-30-2 |

## 変更履歴
| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | 第一スライスを定義 | 500行目安を守り、backend契約を先行するため | T-30-1, T-30-2, T-30-3 |
