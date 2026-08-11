# Knowledge→Project navigation scoped seed CI修正計画

## 依頼・目的・成功指標

- 依頼: PR #191のPlaywright fixtureを現行のowner/space scoped adopted Project repository契約へ合わせる。
- 目的: 製品挙動を変更せず、根拠カードのF5復元と別Project切替時の非表示を実ブラウザで検証する。
- 成功指標: navigation E2E 7件が成功し、全品質ゲートとPR headのCIがgreenになる。

## ユーザーストーリーと受け入れ条件

- ユーザーとして、Knowledgeの根拠から対象Projectの5観点へ移動し、F5後も根拠を確認したい。
  - Given 同じowner/spaceの採用済みProjectと根拠が保存されている
  - When 根拠からProjectを開いてF5する
  - Then 対象Project、選択観点、根拠カードが復元される
- ユーザーとして、別Projectへ切り替えたときに以前の根拠を誤表示してほしくない。
  - Given 根拠の対象Projectとは別のProjectがcurrentである
  - When 画面を再読み込みする
  - Then 別Projectが表示され、根拠カードは表示されない

## 確認事項

- 現行repositoryの保存先は `adoptedProjectStorageKey(ownerId, spaceId)` である。
- scoped envelopeはschemaVersion、ownerId、spaceId、projectsを必須とする。
- 製品コード、storage schema、画面仕様は変更しない。

## スコープ外

- Knowledge、Project、Appの製品ロジック変更
- repository schema変更またはlegacy data migration変更
- composer、export、sidebar、Planの変更

## 実装タスク

1. navigation E2Eのlegacy key書き込み箇所を列挙し、現行scoped envelopeとの差を確認する。
2. fixtureとProject切替操作をscoped key/envelopeへ変更する。
3. F5復元、別Project隔離、5観点keyboard遷移をfocused E2Eで検査する。
4. Vitest、build、Storybook build、pytest、diff checkを実行する。
5. PR headをpushし、exact CI greenとclean worktreeを確認する。

## ADR

- 採用: E2E fixtureをproduction repositoryと同じscoped key/envelopeでseedする。
- 却下: legacy keyを削除して再seedする方法。現行保存契約を直接検証できないため。
- 却下: 製品側でlegacy keyを優先する変更。owner/space隔離を後退させるため。

## 変更履歴

- 2026-08-11: CI失敗の再現原因と修正範囲を確定。
