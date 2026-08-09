# 開発スキル・ライブラリ

最終検証日: 2026-08-09

## 起動規則

作業開始時にこのファイルを読み、現在の工程に対応するスキルを読むこと。Exit Criteria を満たすまで次工程に進まないこと。implementation のループが同一タスクで3周したら、planning の仕様変更手順へ差し戻すこと。

## 工程マップ

```text
planning
  -> implementation <-> testing-and-ci
                    <-> review-and-debug
  -> release-and-security

docs-freshness は全工程で常時適用
```

## ルーティング

| 状況 | 読むスキル |
| --- | --- |
| 「○○をやりたい」を実行可能な計画にする | [planning](planning/SKILL.md) |
| コードまたは設定を変更する | [implementation](implementation/SKILL.md) |
| 次工程のtaskへイベントを渡す、または受領確認を閉じる | [handoff-closure](handoff-closure/SKILL.md) |
| CEO判断が必要な不明点を記録し、自動作業の停止上限を確認する | [ceo-decision-backlog](ceo-decision-backlog/SKILL.md) |
| テスト、CI、レビュー、デバッグ、リリース、ドキュメント更新 | 対応するスキルを追加後に読む |

未追加のスキルへのリンクは、それぞれのPRで追加する。プロジェクト固有の規約は、このライブラリではなく各プロジェクト側に置く。
