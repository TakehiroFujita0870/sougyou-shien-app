# Kadode 開発申し送り

最終更新: 2026-08-09。担当はこの文書と`docs/spec/`を正本として開発を継続してください。

## 現在地

- `main`には継承監査とSDD要件定義が入っています。
- PR #2（`codex/kadode-core-bootstrap`）にはReact/Vite/Tailwind、Storybook a11y、FastAPI、uv、pytest、PR CIがあります。`npm run build`、`npm run build-storybook`、`uv run pytest`はローカル通過済みです。
- 実アプリ機能は未実装です。画面は方向性を示す静的な最小UIです。

## 技術判断

- Frontend: React + Vite + Tailwind CSS。UIはStorybookを必須とします。
- Backend: Python + FastAPI。依存は`uv`だけで管理します。決定的なゲート、遷移、権限、エクスポートをPythonに置き、LLMは起案・反証文の生成に限定します。
- Data: Supabase Auth/Postgres/RLSを予定。実プロジェクトURL・鍵は未設定であり、`.env`へ保存しません。
- Hosting: Vercelを予定。ただしデプロイ・外部公開は未承認です。

## 開発原則

- PRは自動作成・CI確認・マージしてよい。細部の確認待ちで止まらない。
- タケさんへの確認は、製品方針の転換、外部公開、支出、契約、法務、個人情報の外部送信だけに限定します。
- 1PRは1機能。CI不合格は修正し、mainへ直接pushしません（初回リポジトリ初期化の例外は完了済み）。
- 時間駆動の無人ループは導入しない。自動化は品質ゲート付きのPR運用に限定します。

## 次の実装順序

1. PR #2をCI通過後に自動マージする。
2. Supabase migration: `ideas`、`stage_runs`、`death_causes`、`decision_records`、`consents`、`deletion_requests`とowner-based RLS。
3. アイデア登録画面、パイプライン進捗、Storybookの主要画面Storyを実装する。
4. Pythonの決定的Stageゲート（Stage 1の死因3件、Stage 2の品質要件、Stage 4理由必須）をテスト駆動で実装する。
5. LLM実行境界、graveyard検索、エクスポート、削除・同意へ進む。

## 仕様の核

- [PRD](spec/PRD.md)
- [アーキテクチャ](spec/architecture.md)
- [反証エンジン仕様](spec/falsification-engine.md)
- [実装バックログ](spec/backlog.md)

## 注意事項

- `docs/inherited/ai-company-os`と`docs/inherited/mba-practice-app`はサブモジュールです。継承元の作業ツリーを改変しないでください。
- MBA由来のGROWTH_PATTERNS/LESSONSはサブモジュール配下に追跡できないため、必要ならKadode本体の`docs/inherited-reports/`へ移します。
- Xは`x-drafts/`への下書きのみ。投稿APIや自動投稿を実装しません。
