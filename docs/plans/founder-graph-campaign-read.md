# Founder Graph Campaign comparison read adapter 計画

最終検証日: 2026-09-22

## 要望 / ゴール / 成功指標

要望: 既存のowner-scoped GraphReadPortからCampaign比較UIへ渡す値を、Campaign、Run、ReportVersionのsafe fieldへ限定する。

ゴール: Campaign IDを起点に1回のfetchとbounded searchで比較projectionを作り、private/raw input snapshotや結果本文をUIへ渡さない。

成功指標: 合成read portでCampaign 1件、Run 2件、ReportVersion 2件をowner一致・重複排除・固定allowlist付きで返し、別owner、停止、timeout、想定外node typeをfail closedする。

## ユーザーストーリーと受け入れ条件

### US-1

As a Campaign比較UI, I want owner-scoped safe projectionを受け取りたい, so that 複数Runと8章ReportDiffを表示できる。

Given: GraphReadPortが対象Campaign、同一CampaignのRun、ReportVersionを返す。

When: `load_campaign_comparison`をownerとCampaign IDで呼ぶ。

Then: Campaignの目的・状態・試行予算、RunのID・状態・model snapshot、ReportVersionの8章safe projectionだけを返す。

### US-2

As a local operator, I want read failureをUI状態へ変換できる値で受け取りたい, so that 停止中に空成功を表示しない。

Given: owner不一致、not-found、timeout、unavailable、想定外node typeが発生する。

When: adapterがGraphReadPortを呼ぶ。

Then: 元のGraphReadError分類を保持し、private fieldを含む部分結果を返さない。

## 質問リスト

なし。実データ接続とMCP transportは別ゲートへ残す。

## スコープ外

- Neo4j driver、MCP transport、FastAPI route、Deep Research、write-back。
- ReportVersionの作成・編集・削除、Campaign state transition。
- input snapshot、results、failures、contact、private_notesの返却。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
| --- | --- | --- | --- |
| T-CREAD-01 | pure safe projection | 検査: Campaign / Run / ReportVersionの固定allowlist、scalar化、重複排除をfocused pytestで確認する | 既知 |
| T-CREAD-02 | bounded GraphReadPort composition | 検査: fetch 1回、search 1回、owner / node type / campaign_id filter、error propagationをfake portで確認する | 類推可能 |
| T-CREAD-03 | implementation memo | 検査: focused pytest、py_compile、git diff --checkを記録する | 既知 |

## ADR

| 判断 | 選択と理由 | 却下案と理由 | 結果 |
| --- | --- | --- | --- |
| 読み取り境界 | GraphReadPortだけを依存にし、Neo4jやMCPへ直接依存しない | adapterがDB driverを直接生成する案は停止・owner・テスト境界を破るため却下 | 実DB接続はcomposition rootの後続タスクへ残る |
| 検索回数 | Campaign fetch 1回とcampaign IDのbounded search 1回に限定する | 全graph scanやRunごとのfetchは速度・timeout境界を広げるため却下 | Reportは明示IDがある場合だけfetchする |
| projection | 正のallowlistでscalarとReportDiffへ渡す | dataclass全fieldをspreadする案はinput snapshotとprivate leakageを招くため却下 | UI componentと同じsafe field契約を共有する |

## 実装メモ

- `backend/dots/founder_graph_campaign_read.py` に immutable `CampaignComparisonProjection` と `load_campaign_comparison` を追加する。
- GraphReadPortの停止・timeout・not-foundは握り潰さず、そのまま呼出元へ伝播する。検索結果が別ownerまたは別Campaignなら除外する。

## 検査結果

- `uv run --isolated --python 3.14 --with pytest pytest -q backend/tests/test_founder_graph_campaign_read.py`: 3 passed。
- 実Neo4j、FastAPI route、MCP transportへのruntime接続は未検査。

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
| --- | --- | --- | --- |
| 2026-09-22 | Campaign比較のsafe read adapter計画を追加 | UIと実DB接続の間に固定projection境界を置くため | T-CREAD-01〜03 |
| 2026-09-22 | bounded GraphReadPort compositionと3件のfocused testsを実装 | UIへ渡すCampaign / Run / ReportVersionのallowlistをruntime接続前に固定するため | T-CREAD-01〜03 |
