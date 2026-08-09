# Issue #75: Pro「準備中」表示 計画

最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

要望: Free、Standard、Pro 2,980円/月を比較できるPlanSelectionを表示し、Proは準備中として選択・申込み・決済を発生させない。

ゴール: Proを同一の比較グリッドに表示し、利用不可の理由をキーボード利用者とスクリーンリーダー利用者に伝える。

成功指標: 390pxとdesktopのStory、a11yテスト、PlanSelectionテストでProの比較表示・利用不可表示・選択イベント非発火を確認できる。

## ユーザーストーリーと受け入れ条件

### US-1: プラン比較

As a プランを比較する利用者, I want Free、Standard、Proを同じ比較領域で読める, so that Proが将来提供予定であることを理解できる。

Given: PlanSelectionを390pxまたはdesktop幅で表示している。

When: 利用者がプラン比較領域を読む。

Then: Free、Standard、Proの3カードが同じ比較グリッドにあり、Proカードに「月額2,980円」と「準備中」が表示される。

### US-2: Proの利用不可状態

As a キーボードまたはスクリーンリーダー利用者, I want Proが現在利用できない理由を知る, so that 誤って申込みや決済が行われたと誤認しない。

Given: Proカードが表示されている。

When: 利用者がProカードの見出し、説明、利用不可コントロールを読む。

Then: 「現在は選択、申込み、決済できません。」という理由と、disabledの「準備中・現在利用不可」コントロールを確認できる。

### US-3: ローカル選択の安全性

As a ローカル/fakeモードの利用者, I want Pro操作で状態変更が起きない, so that 外部契約または決済が始まらないことを確認できる。

Given: currentPlanがfreeで、onApplyPlanを監視している。

When: Proのdisabledコントロールへの操作を試みる。

Then: onApplyPlanは呼び出されず、FreeまたはStandardのローカル確認フローは従来どおり動作する。

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| なし | 割当済み受入条件で実装可能 | なし | なし |

## スコープ外

- `App.jsx`、WorkspaceShell、account footer、navigation、shared style、global tokenの変更。
- plan repositoryのapply可能プラン変更、auth/runtime/API、外部決済、Stripe、支出、契約。
- Proの自動深掘り、メール送信、外部サービス接続。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-1 | `PlanSelection.jsx`の3カード比較とPro利用不可セマンティクス | 検査: `PlanSelection.test.jsx`の比較・disabledテストが成功 | 既知 |
| T-2 | 390px/desktop Story | 検査: `PlanSelection.stories.jsx`に390pxとdesktop viewport設定がある | 既知 |
| T-3 | a11yと非発火のテスト | 検査: `npm run test -- src/components/PlanSelection.test.jsx`が成功 | 既知 |
| T-4 | 最終検査 | 検査: `npm run test`、`npm run build`、`npm run build-storybook`、`git diff --check`が成功 | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| Proの比較表現 | Free/Standardと同じfieldset内の非選択カードにする。既存のradio選択をProへ拡張せず、比較可能性と安全性を両立する。 | Proをradioとして追加する案は、repositoryがFree/Standardだけをapply可能とする契約に反するため却下。別のカードグリッドを作る案は、比較が分断されるため却下。 | 実装する。 |
| 利用不可の伝達 | Proカードの説明とdisabledボタンを`aria-describedby`で結び、可視テキストも残す。 | 色またはbadgeだけで伝える案は、非視覚利用者と高コントラスト環境で状態を保証できないため却下。 | 実装する。 |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | 初版作成 | Issue #75のpresentational/a11y第一sliceを固定 | T-1、T-2、T-3、T-4 |
