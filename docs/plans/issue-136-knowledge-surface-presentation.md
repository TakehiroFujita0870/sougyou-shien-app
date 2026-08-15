# Issue #136 Knowledge surface presentation 計画
最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

要望: #136でmerge済みのKnowledge metadata契約を使い、Knowledge surfaceのpresentationを1PRで実装する。初回登録asset、背景とProject概要付き意思決定、資料の確認・追加・削除、Knowledge Dots. AI composerを表示する。admin/demo fixtureはproductionデータから分離する。

ゴール: desktopと390pxで、本人所有のKnowledge metadataを起点に、assetの状態・出典・Project文脈・意思決定・composerを確認できるpresentation surfaceを提供する。

成功指標: Storyとcomponent testで、初回asset、metadata契約に沿う背景/Project概要付きdecision、資料確認/追加/削除、PIIなしdemo fixture、keyboard/a11y、390px横overflowなしを観測できる。

## ユーザーストーリーと受け入れ条件

### US-136-1 Knowledge assetを確認する
As a 利用者, I want 初回登録assetとmetadataの状態・出典・Project文脈を確認したい, so that 何を根拠に使えるか判断できる。
Given: owner/space内のactive metadataとProject概要がある。
When: Knowledge surfaceを開く。
Then: asset名、version、解析状態、出典、背景、Project概要がPIIなしで表示される。

### US-136-2 資料を管理する
As a 利用者, I want 資料を追加、確認、削除したい, so that Knowledgeを最新状態に保てる。
Given: Knowledge surfaceを表示している。
When: 資料追加または削除確認を操作する。
Then: add/remove callbackが対象metadataだけで呼ばれ、deleted assetとunavailable referenceは表示されない。

### US-136-3 意思決定を確認する
As a 利用者, I want 背景とProject概要を含む意思決定を確認したい, so that 判断理由を次回の検討へ引き継げる。
Given: decision recordに背景、Project概要、理由、状態がある。
When: decisionを開く。
Then: 背景、Project概要、本人判断、理由が区別されて表示される。

### US-136-4 Dots. AIへ相談する
As a 利用者, I want Knowledge context付きcomposerを使いたい, so that 資料と判断を起点に次の問いを入力できる。
Given: desktopまたは390pxのKnowledge surfaceを表示している。
When: keyboardでcomposerへ移動し入力する。
Then: named textarea、Enter/Shift+Enter説明、44px以上の送信操作、visible focusがある。

## 質問リスト
| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| なし | #136 metadata契約と既存presentation contractを採用する | 統合・リリース管理部 | 実装開始前 |

## スコープ外
- App.jsx、Home、Project、WorkspaceShell、conversation/project workflow、API、global stylesの変更。
- production adapter、Supabase、外部AI、実ユーザーデータ、PIIを含むfixture。
- shadcn全画面contractが提供する前の新規runtime wiring。

## タスク
| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-136-1 | admin/demo分離fixtureとKnowledge presentation component | 検査: `KnowledgeSurface.test.jsx`でasset、decision、削除、PII境界を確認 | 既知 |
| T-136-2 | desktop/390px Storyとkeyboard/a11y contract | 検査: `KnowledgeSurface.stories.jsx`のDesktop/Mobile/Empty/Loading/Error exportとplay assertion | 類推可能 |
| T-136-3 | PR前品質検査 | 検査: `npm run test`、`npm run build`、`npm run build-storybook`、`git diff --check` | 既知 |

## ADR
| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| fixture境界 | `src/fixtures/knowledge-admin-demo.json`をpresentation専用fixtureとして使い、production adapterへimportしない | production seedへの混在はPIIとデモデータ漏洩境界を壊すため却下 | demo-only import |
| surface wiring | componentとStoryを追加し、App/Shellは変更しない | App wiringは依存中のUI基盤・workflow所有権と衝突するため却下 | 後続assignmentで接続 |
| styling | 既存Tailwind utilityとnative HTMLを使う | global style・新規依存追加はscope外のため却下 | 既存contractへ追従 |

## 変更履歴
| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | 初版 | #136のKnowledge presentationを単一PRに固定 | T-136-1〜3 |
