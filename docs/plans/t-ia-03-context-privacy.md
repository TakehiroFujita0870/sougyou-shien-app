# T-IA-03 context/privacy boundary 計画

最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

要望: Kadode AI context/privacy boundary first sliceとして、決定的なlocal-only snapshot schemaとallowlistを提供する。

ゴール: Home、Project、KnowledgeのUI状態から、AIへ渡してよい識別子・表示名・locator・revision・選択状態・明示的な未保存変更のmetadataだけを、owner境界と削除・権限変更伝播を保ったsnapshotへ変換する。

成功指標: snapshotがallowlistだけを含み、facts/inferenceとsource locatorを区別し、別owner・削除済み・権限喪失のentityを除外し、入力順に関係なく同じsnapshotを返すことを契約テストで確認する。

## ユーザーストーリーと受け入れ条件

### US-IA-03-1
As a Kadode user, I want my current surface context to be explicit, so that AI output can identify its permitted source.

Given: Home、Project、Knowledgeのsurface stateがある。
When: local snapshot adapterを実行する。
Then: surface、selected project/asset/decisionのid、displayName、locator、revision、selection、selected entityのexplicit dirty metadataだけを返す。

### US-IA-03-2
As a Kadode user, I want private or unavailable data excluded, so that it is never included in AI context.

Given: raw upload body、hidden knowledge、別owner entity、token、secret、profile detail、削除済みまたは権限喪失entityが入力にある。
When: local snapshot adapterを実行する。
Then: snapshotにそれらの値、またはそれらを復元できるfieldは含まれない。

### US-IA-03-3
As a Kadode user, I want facts and inference distinguished, so that I can judge the basis of AI context.

Given: factとinferenceのsource entriesがある。
When: local snapshot adapterを実行する。
Then: kindと必須source locatorを保ち、空locatorのentryを除外する。

### US-IA-03-4
As a Kadode user, I want a deterministic local snapshot, so that F5 hydration and tests do not alter its result.

Given: 同じ許可済みstateを異なる入力順で渡す。
When: local snapshot adapterを実行する。
Then: canonical key orderとentity orderを持つ同一snapshotを返す。

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| Q-IA-03-1 | profile summaryに許可する非機微field | 基盤・認証部と会話体験・プロジェクト部 | T-IA-09開始前 |

## スコープ外

- 外部AI/API送信、実OAuth、token、実RLS migration、vector DB、raw upload本文、未保存text値の保存または送信。
- App、WorkspaceShell、style、candidate decision workflowの変更。
- 同意なしprofile詳細、未表示knowledge、他user情報のsnapshot化。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-IA-03-1 | allowlist schemaとpure local adapter | 検査: `npm run test -- --run src/context/contextSnapshot.test.js` | 既知 |
| T-IA-03-2 | owner、deleted、permission、source、dirty metadata境界の契約test | 検査: `npm run test -- --run src/context/contextSnapshot.test.js` | 既知 |
| T-IA-03-3 | context/privacy boundary計画 | 検査: planning Exit Criteriaの検索とレビュー | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| snapshot形式 | pure functionがallowlist inputからplain JSONを返す。dirty stateはselected entityの`entityId`と`dirty: true`だけを返す。network・browser stateなしで決定的に検証できる。 | UI componentが任意stateまたはdirty text値を読む方式はprivacy境界を分散するため却下。 | 採用 |
| entity可視性 | owner一致、非deleted、permission有効を満たすentityだけを含める。 | 後続層での除外はraw dataがboundaryを越えるため却下。 | 採用 |
| source根拠 | facts/inferenceを`kind`で明示し、locatorが空のsourceは除外する。 | inferenceをfactとして扱う方式は根拠を曖昧にするため却下。 | 採用 |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | 初版 | ASSIGNMENTのallowlist・privacy契約を実装可能な単位へ固定 | T-IA-03-1から3 |
| 2026-08-09 | P1修正: dirty changeのtext値を除外し、selected entityのmetadataへ限定 | raw/hidden/secretの未保存入力をsnapshotへ入れない | T-IA-03-1から2 |
