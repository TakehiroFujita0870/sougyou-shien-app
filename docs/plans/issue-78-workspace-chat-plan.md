# T-IA-00 Home / Project / Knowledge IA reset 計画

最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

要望: 旧idea stateをHome、Project、Knowledgeの3 surfaceへ安全に対応づけ、IA reset後の会話体験を段階実装できる計画にする。

ゴール: Home supervisorとproject ID単位会話を混同せず、allowlist context snapshotと明示判断を持つ移行順を定義する。

成功指標: IA reset merge前にruntime変更を加えず、後続担当がcontext snapshot、採用、保留、理由付き却下を検証可能にする。

## ユーザーストーリーと受け入れ条件

### US-IA-01 Homeで横断相談する

As a 利用者, I want Home supervisorへspace全体の相談をする, so that projectを決める前の情報を整理できる。

Given: Home surfaceが利用可能である
When: starter promptまたは入力を選ぶ
Then: allowlistされたprofile summary、active project summary、available knowledge locatorだけのcontext snapshotを確認できる。

### US-IA-02 Project会話を分ける

As a 利用者, I want project IDごとの会話を使う, so that 別projectの会話を混ぜない。

Given: project IDが選択されている
When: project会話を再開する
Then: 同じproject IDの会話だけを表示し、Home会話を表示しない。

### US-IA-03 候補を判断する

As a 利用者, I want inline artifactを確認して採用、保留、理由付き却下を選ぶ, so that AIが自動でprojectを確定しない。

Given: 会話から候補artifactが提示されている
When: 明示確認操作で採用、保留、または却下を選ぶ
Then: 採用だけがproject化候補として保存され、却下理由は同一前提の再提示を抑制する。

## スコープ外

- IA reset merge前のApp、WorkspaceShell、shared style、nav、tokens、独立chat route
- `kadode:workspace-chat`、外部送信、外部AI、Supabase、owner/grant入力、保存先の自動変更
- runtime component、Storybook、API、auth、entitlementの変更

## 旧idea state mapping

| 旧state | IA reset後の扱い | 移行条件 |
| --- | --- | --- |
| idea conversation | Home supervisorの会話候補 | IA reset後にconversation providerを決定 |
| idea candidate preview | Project inline artifact | 明示採用操作とproject IDを持つ |
| local draft | current surfaceの未送信draft | hydrate競合テストを保持 |
| file reference | Knowledge locator | availableのみをallowlistへ入れる |

## タスク

| ID | 成果物 | 完了判定 | 不確実性 |
| --- | --- | --- | --- |
| T-IA-00 | このstate mappingと段階計画 | 検査: 3 surface、allowlist、明示判断、スコープ外をレビュー | 既知 |
| T-IA-01 | Home supervisor context provider | 検査: context snapshotのallowlist test | 類推可能 |
| T-IA-02 | project ID会話とdraft hydrate | 検査: project分離、F5、390px、keyboard test | 類推可能 |
| T-IA-03 | inline artifact判断 | 検査: 採用、保留、理由付き却下、明示確認 test | 類推可能 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| surface | Home / Project / Knowledgeへ分離 | 独立chat routeはIAと会話責務を重複するため却下 | IA reset後に実装 |
| context | allowlist snapshotだけをproviderが渡す | owner/grantをUIから渡す案はfixed-principal境界に反するため却下 | external送信なし |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | T-IA-00へ再編 | CEO確定IAへ整合しruntimeを除外 | T-IA-00からT-IA-03 |
