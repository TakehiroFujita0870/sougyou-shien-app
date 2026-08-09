# #74 Project surface presentation 計画

最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

要望: Project surfaceのfirst viewportに、静かなshell、選択中projectのidentity/status、Kadode AI composer、5つの事業検討sectionを表示する。

ゴール: APIやdomain計算に接続せず、決定的fixtureを使ってDesktopと390pxのProject presentationを確認できるようにする。

成功指標: ProjectのEmpty/Populated/Loading/ErrorをStoryで再現でき、first viewportにcomposerとproject summaryがあり、5 sectionがscannableでoverflowしない。

## ユーザーストーリーと受け入れ条件

### US-1

As a 起業準備者, I want Projectを開いた直後にproject identityとcomposerを見たい, so that 現在の検討対象と次の入力場所を同時に理解できる。

Given: Project surfaceをDesktopまたは390pxで開いている。

When: first viewportを確認する。

Then: compact project identity/status、Kadode AI composer、EmptyまたはPopulatedのartifactが表示され、巨大headingや大面積空カードは表示されない。

### US-2

As a 起業準備者, I want どんな事業・市場・競合・利益・実現性を一覧で確認したい, so that 検討の抜けを把握できる。

Given: Populated Project fixtureを表示している。

When: 5つのsectionを上から確認する。

Then: 各sectionが見出し、短いstatus、内容または未確認表示としてscannableに並ぶ。

### US-3

As a キーボード利用者, I want Projectのcomposerとsectionへ順序よく移動したい, so that ポインタなしで状態を確認できる。

Given: Project surfaceが表示されている。

When: Tab移動、Enter送信、Shift+Enter改行、reduced-motion設定を使う。

Then: visible focus、screen-reader label、44px target、motionなしでも理解できるstatusが確認できる。

## 質問リスト

| ID | 質問 | 決定者 | 期限 |
| --- | --- | --- | --- |
| Q-1 | Project fixtureの表示文言をAPI契約に先行して固定するか | プロダクトUI・デザインシステム部 | 実装前のコード調査 |

## スコープ外

- #131 API、fetch、外部サービス、domain計算、project repository、auth、App hydrationの変更。
- Home conversation workflow、candidate decision workflow、selected surface persistenceの変更。
- Projectの作成、編集、削除、採用、保留、却下のruntime処理。
- shared styles/global tokensの変更、巨大な新規UI基盤、別top-level navの追加。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-1 | deterministic Project presentation component | 検査: component testでEmpty/Populated/Loading/Errorと5 sectionを確認 | 類推可能 |
| T-2 | Desktop / 390px / keyboard / axe Stories | 検査: `npm run build-storybook`とfocused testが成功 | 類推可能 |
| T-3 | Project surface接続 | 検査: App testでProject選択後のcomposerとsummaryを確認 | 類推可能 |
| T-4 | 最終検査 | 検査: `npm run test`、`npm run build`、`npm run build-storybook`、`uv run pytest`、`git diff --check`が成功 | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| fixture境界 | propsでdeterministic stateを注入し、runtime APIを呼ばない。 | fetchを直接呼ぶ案は#131依存と外部接続を持ち込むため却下。 | 実装する。 |
| layout | compact identityの下にcomposer、5 sectionを1主カラムで配置する。 | 大きなカードを左右に並べる案は390pxのscanとfirst viewportを損ねるため却下。 | 実装する。 |
| status | Empty/Populated/Loading/Errorを短いtext statusで表示する。 | statusを色やanimationだけで示す案はa11yとreduced-motionを損ねるため却下。 | 実装する。 |

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-08-09 | 初版作成 | #74 Project surface presentation sliceを固定 | T-1からT-4 |
