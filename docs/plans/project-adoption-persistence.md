# 採用プロジェクト永続化計画

最終更新日: 2026-08-09

## 目的

Home で利用者が採用した候補を、同一 owner / space の Project に表示し、再読込後も安全に復元する。採用済みデータがないときだけ合成デモを表示する。

## ユーザーストーリーと受入基準

### US-PAP-01

As a 利用者, I want Home で採用した候補を Project で読み直したい, so that 会話で固めた判断を次の検討に引き継げる。

Given: Home で title / fact / inference を持つ候補を採用している
When: Project を開く、または F5 で再読込する
Then: 同じ owner / space の採用済み候補が title / fact / inference / reason / status とともに表示され、合成デモに戻らない

### US-PAP-02

As a 利用者, I want 他の空間の候補と分離したい, so that 自分以外または別空間の事業情報を混在させない。

Given: 同一ブラウザに異なる owner または space の保存記録がある
When: 現在の owner / space で repository を読込む
Then: 現在の owner / space の採用済み候補だけが返る

### US-PAP-03

As a 利用者, I want 壊れた保存記録でも画面を安全に開きたい, so that 既存の記録を不意に上書きしない。

Given: 保存値が壊れている、または読込が失敗する
When: アプリを起動する
Then: repository は安全な空状態を返し、保存値を上書きせず、Project は合成デモを表示できる

## データ境界

- localStorage のみ。外部 API、認証通信、個人情報送信は行わない。
- schemaVersion、ownerId、spaceId、id、title、fact、inference、reason、status を検証する。
- Project は hydrated state が ready になるまで合成デモを確定表示しない。
- 既存レコードの破損時は quarantine 相当の空読込とし、write は発生させない。

## タスク

| ID | 内容 | 依存 | 受入 |
| --- | --- | --- | --- |
| PAP-01 | owner / space scoped project repository | なし | schema、隔離、破損、stable load の単体テスト |
| PAP-02 | App の採用・hydrate 接続 | PAP-01 | 採用→Project→F5 の統合テスト |
| PAP-03 | Project fixture 選択 | PAP-02 | 採用済み時は title / fact / inference、未採用時のみデモ |

## ADR

| 選択 | 理由 | 却下案 |
| --- | --- | --- |
| local repository を App 境界で一度 hydrate | F5 復元と安全な read failure を一箇所で扱える | ProjectSurface が直接 localStorage を読む案は presentation と保存を混在させるため却下 |
| owner / space で永続値をフィルタ | 将来の認証/RLS 置換と同型にできる | browser 全体で一件だけ保存する案は空間境界を失うため却下 |

## スコープ外

- Project の会話 UI、Home の見た目、Knowledge、Account/Plan、音声、外部サービス、モバイル最適化。
