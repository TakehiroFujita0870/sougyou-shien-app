# CIの使い分け

最終更新: 2026-09-23

## 普段の変更

pull requestとmainへの反映では、必須の`quality`確認が自動で動く。この確認は次だけを対象にする。

- JavaScriptの基本テスト
- JavaScriptのビルド
- Pythonの基本テスト

通常の確認では、ブラウザを実際に操作する確認、Storybookの見た目比較、PDF・DOCXの全ページ確認、LibreOfficeの導入を行わない。

## 節目の確認

画面、Storybook、PDF、DOCX、画面録画、帳票出力を変更した場合は、GitHubのActions画面から`CI` workflowを手動開始する。手動開始では、通常の確認に加えて既存の重い確認と証跡保存を実行する。

実行する節目の例は次のとおり。

- Founder Graphの画面を本体データへ接続したとき
- PDFまたはDOCXの出力内容を変更したとき
- 主要な画面の配置、キーボード操作、見た目を変更したとき
- MVPの受け入れ確認を行うとき

## 失敗時の扱い

通常の確認が失敗した場合はmainへ取り込まない。手動の節目確認が失敗した場合は、失敗した画面または帳票の変更を直してから同じworkflowを再実行する。

## GitHub操作の頻度

ローカルでは小さな編集と確認を続ける。意味のある一まとまりができた時点でcommit、push、pull requestを行う。毎回の編集でGitHubへ送る必要はない。

## 関連ファイル

- [`../../.github/workflows/ci.yml`](../../.github/workflows/ci.yml)
- [`../plans/ci-lightening-and-legacy-disposition.md`](../plans/ci-lightening-and-legacy-disposition.md)
