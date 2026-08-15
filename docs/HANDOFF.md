# Dots. 開発申し送り

最終更新: 2026-08-09。担当はこの文書と`docs/spec/`を正本として開発を継続してください。

## 現在地

- PR #2のReact/Vite/Tailwind、Storybook a11y、FastAPI、uv、pytest、PR CIは`main`へマージ済みです。
- PR #3のowner-based RLS、PR #5のアイデア入力・進捗UI、PR #6の`AGENTS.md`とモデル更新方針は`main`へマージ済みです。
- 初回リリースはFreeとStandardです。Proの自動調査とメール配信は利用量・原価データの蓄積後に再計画します。

## 技術判断

- Frontend: React + Vite + Tailwind CSS。UIはStorybookを必須とします。
- Backend: Python + FastAPI。依存は`uv`だけで管理します。権限、課金上限、削除を決定的なコードに置き、LLMは対話、仮説カード、調査レポートを生成します。
- Data: Supabase Auth/Postgres/RLSを予定。実プロジェクトURL・鍵は未設定であり、`.env`へ保存しません。
- Hosting: Vercelを予定。ただしデプロイ・外部公開は未承認です。

## 開発原則

- PRは自動作成・CI確認・マージしてよい。細部の確認待ちで止まらない。
- タケさんへの確認は、製品方針の転換、外部公開、支出、契約、法務、個人情報の外部送信だけに限定します。
- 1PRは1機能。CI不合格は修正し、mainへ直接pushしません（初回リポジトリ初期化の例外は完了済み）。
- 時間駆動の無人ループは導入しない。自動化は品質ゲート付きのPR運用に限定します。

## 次の実装順序

1. 初回対話で「あなたの情報」を作成・更新できるUXを計画する。
2. 対話からアイデアストックと編集可能なアイデア仮説カードを作る。
3. 横断調査の3スパイクを行い、Web検索、特許検索、ファイル解析の方式を決める。
4. owner-based RLSを維持して、個人資料と意思決定記録のハイブリッド検索を追加する。
5. 「市場の見込み」「競合との違い」「攻めどころの特定」と引用付きレポートへ進む。
6. 事業のタネを5観点で具体化し、採算・実現性・ローカル事業計画書exportを個別PRで進める。

## 仕様の核

- [PRD](spec/PRD.md)
- [アーキテクチャ](spec/architecture.md)
- [仮説検証・調査支援仕様](spec/falsification-engine.md)
- [実装バックログ](spec/backlog.md)
- [横断調査・個人ナレッジ・意思決定記憶 計画](spec/research-memory-plan.md)
- [事業のタネを5観点で具体化する計画](spec/business-seed-plan.md)

## 注意事項

- `docs/inherited/ai-company-os`と`docs/inherited/mba-practice-app`はサブモジュールです。継承元の作業ツリーを改変しないでください。
- MBA由来のGROWTH_PATTERNS/LESSONSはサブモジュール配下に追跡できないため、必要ならDots.本体の`docs/inherited-reports/`へ移します。
- Xは`x-drafts/`への下書きのみ。投稿APIや自動投稿を実装しません。
