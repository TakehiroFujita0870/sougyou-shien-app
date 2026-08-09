# 役割別モデルプロファイル計画

最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

要望: 部門の役割ごとにモデルと努力量を固定し、handoff時に同じoverrideで新turnを起動する。

ゴール: CEO室と統合部はTerra/medium、実装部はLuna/lowを使い、利用不能時だけ明示BLOCKEDする。

成功指標: 正本に役割表、model_unavailable、ASSIGNMENT/DEPENDENCY_READYの必須fieldsが記録される。

## ユーザーストーリーと受け入れ条件

### US-1

Given: 統合部が実装部へASSIGNMENTまたはDEPENDENCY_READYを送る
When: payloadと新turnを作る
Then: 受信部の指定 `model` と `thinking` がpayloadとturn overrideで一致する。

### US-2

Given: 指定モデルを利用できない
When: 担当部が開始できない
Then: `reason: model_unavailable` のBLOCKEDを統合部へ送る。統合部自身の場合はCEO室へ送り、別プロファイルへ無断切替しない。

## スコープ外

- 定期ポーリング、モデルの自動fallback、実装内容の変更

## ADR

| 判断 | 選択と理由 | 結果 |
| --- | --- | --- |
| 統治プロファイル | CEO室・統合部をTerra/mediumに固定 | 高い判断密度を維持する |
| 実装プロファイル | 全実装部をLuna/lowに固定 | 実装handoffを一定品質・コストで運用する |
| 障害時 | model_unavailableだけBLOCKED | 暗黙のfallbackを防ぐ |

## 変更履歴

| 日時 | 変更 | 理由 |
| --- | --- | --- |
| 2026-08-09 | 初版 | 役割別プロファイルの固定 |
