# 管理者demo用仮想事業データセット 計画

## 要望 / ゴール / 成功指標

要望: PIIを含まない日本語の仮想事業データを、Home会話からProject、5観点、採算、実行、Knowledge、意思決定まで一貫したfixtureとして提供する。
ゴール: 管理者demoで合成データであることを明示し、参照IDが相互に解決できる決定的schemaを提供する。
成功指標: 同一fixtureのmodel_dumpが一致し、5観点・競合3分類・損益分岐・project参照・provenanceのpytestが通る。

## ユーザーストーリーと受け入れ条件

### US-DEMO-01 管理者
As a demo administrator, I want one coherent Japanese dataset, so that the product flow can be demonstrated without real user data.
Given: 合成fixtureを生成する。
When: datasetを読み込む。
Then: Home会話、採用project、5観点、競合、財務、実行、Knowledge、意思決定が同じproject IDで参照できる。

### US-DEMO-02 誤認防止
As a demo viewer, I want provenance to be visible, so that synthetic content is not mistaken for a real case.
Given: datasetをJSONへ変換する。
When: provenanceを確認する。
Then: `synthetic_demo`と「実在の人物・企業・取引を表しません」が含まれ、銀行情報や認証情報が含まれない。

## スコープ外

- UI、API、外部投稿、外部サービス、実ユーザー情報、実在企業・金融機関の推薦。
- fixtureを本番DBへseedする処理、画像・PDF・DOCX生成。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-DEMO-01 | `AdminDemoDataset` schemaとfixture builder | 検査: 決定性、5観点順、project/source/decision参照pytest | 既知 |
| T-DEMO-02 | 合成provenanceとPII禁止契約 | 検査: `synthetic_demo`、notice、禁止語のpytest | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| fixture形式 | Pydanticの不変な構造化モデルをbuilderから返す | JSON文字列だけのfixtureは参照整合性を実行時に検証できないため却下 | adapterがJSONへ変換可能な決定的schemaになる |
| provenance | `synthetic_demo`と明示noticeを必須値にする | demo環境名だけに依存する案は転載時に誤認するため却下 | データ単体で合成と分かる |
