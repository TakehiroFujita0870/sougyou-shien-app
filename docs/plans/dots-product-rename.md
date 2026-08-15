# Dots. プロダクト名称変更計画

最終検証日: 2026-08-15

## 要望 / ゴール / 成功指標

要望: 経営者決裁により、正式表記Dots.へ変更し、リポジトリ内の旧名称を排除する。技術識別子はdots、DOTS_、dots_、Dotsに統一する。開発版の既存保存データは破棄し、旧名称への後方互換を持たない。

ゴール: Dots.がUI、文書、設定、コード識別子、テスト、CI、ローカル保存、DB schemaで唯一の現行名称になる。

成功指標: 追跡対象ファイルに旧製品名の各表記が残らず、アプリ、Storybook、backend test、frontend test、buildが成功する。

## ユーザーストーリーと受け入れ条件

### US-1 表示名称

As a 利用者, I want 画面と生成物でDots.を読む, so that 一貫した製品名称を認識できる。

Given: アプリ、Storybook、HTMLメタデータ、export生成物を開く
When: 製品名称を読む
Then: 表示名はDots.であり、旧製品名、DOTS、dots.、単数のDotは表示されない。

### US-2 開発識別子

As a 開発者, I want 技術識別子がDots規約で統一されている, so that 検索、運用、保守で名称が分裂しない。

Given: package、Python package、環境変数、CSS class、Story、CI artifact、localStorage keyを確認する
When: 技術識別子を検索する
Then: packageとディレクトリはdots、環境変数はDOTS_、DB接頭辞はdots_、CSSとコンポーネント接頭辞はDotsである。

### US-3 開発版データ

As a 開発者, I want 旧名称の保存形式を廃止する, so that Dots.の初期状態を単一形式で検証できる。

Given: 旧名称のlocalStorage値または旧migration名がある
When: Dots.版を起動またはschemaを検証する
Then: 旧値を読まず、dots: keyとdots_ schemaだけを使用する。

### US-4 文書と継承資料

As a 利用者, I want 現行文書がDots.を正しく説明する, so that 製品思想と実装方針を同じ名称で参照できる。

Given: docs、x-drafts、リポジトリ運用文書、継承文書を読む
When: 現行プロダクトへの言及を確認する
Then: 現行名称はDots.であり、継承元を明示する原文引用は改変しない。

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| Q-1 | VercelとSupabaseの表示名は接続権限を得た別作業で変更するか | CEO | リポジトリPR完了前 |
| Q-2 | og:imageの新規画像素材を提供するか | CEO | メタデータPR開始前 |

## スコープ外

- GitHub repository slug、リモートURL、ローカルclone名の変更。
- 実Supabaseデータ、実ユーザーのlocalStorage、Vercel、Supabaseの管理画面変更。Q-1が解消された別作業で扱う。
- 新規faviconまたはog:image画像の制作。既存素材の名称とaltだけを変更する。
- 継承元を明示する原文引用の改変。
- 旧名称データの移行、fallback、互換API、read-repair。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-1 | 本計画、旧名称監査、置換規約 | 検査: planning Exit Criteriaと旧製品名検索の対象一覧をレビュー | 既知 |
| T-2 | frontend、Storybook、HTML、localStorage、JS testのDots識別子 | 検査: `npm run test`、`npm run test:a11y`、`npm run build`、`npm run build-storybook` | 類推可能 |
| T-3 | Python package、API表示、環境変数、backend testのdots識別子 | 検査: `uv run pytest`と`python -c "import dots_api"` | 類推可能 |
| T-4 | Supabase migration名とschema内のdots_接頭辞、schema test | 検査: `uv run pytest backend/tests/test_supabase_schema.py backend/tests/test_idea_definition_migration.py` | 類推可能 |
| T-5 | CI、全現行文書、x-drafts、非引用の継承文書、ファイル名 | 検査: 旧製品名検索が0件であり、継承引用を目視確認 | 類推可能 |
| T-6 | 横断回帰と最終旧名称監査 | 検査: `npm run test`、`npm run build`、`npm run build-storybook`、`uv run pytest`、`git diff --check`、旧名称検索 | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と却下理由 | 結果 |
| --- | --- | --- | --- |
| 既存localStorage | 旧keyを読まず、新dots: keyだけを使用する。開発版のデータ破棄を許可されたため。 | 旧keyを読んでdots:へ移す案は旧名称互換コードを残すため却下。 | 採用 |
| DB schema | 初期migrationをdots_名とdots_接頭辞へ置換する。実データ接続前であり、破壊的変更を許可されたため。 | rename migrationを追加する案は旧schemaを残すため却下。 | 採用 |
| Python package | backend/dotsへrenameし、importを更新する。 | import aliasを維持する案は旧識別子を残すため却下。 | 採用 |
| 継承資料 | 現行プロダクトへの記述をDots.へ改め、継承元を明示する引用は原文のまま残す。 | 継承資料全体を無条件に置換する案は原文引用の保全規則に反するため却下。 | 採用 |
| 外部表示名 | repositoryの追跡対象外としてQ-1の回答後に別作業で変更する。 | 認証なしで外部管理画面を変更する案は実行不能なため却下。 | 保留 |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-15 | 初版作成。開発版データの破棄と後方互換なしを記録。 | CEO決裁の名称変更指示。 | T-1からT-6 |
