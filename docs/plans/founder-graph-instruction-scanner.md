# Founder Graph instruction scanner bounded plan

## 目的と境界

T-FG-10の第一sliceとして、本人のFounder Graphに関係する`AGENTS.md`と`SKILL.md`を安全に観測し、path、scope、hash、mtime、非機密summary、変更・欠落状態を返すscannerを実装する。ファイル本体を正本として残し、Dots側は参照とrevision候補だけを保持する。

scannerは指定root配下の許可ファイルだけを読む。symlink/reparse、root外、別名ファイル、秘密値の取り込みを拒否または除外し、AGENTS/SKILLを自動編集しない。

## 受け入れ条件

- `AGENTS.md`と`SKILL.md`だけを対象にし、指定root外・symlink・別ファイルを取り込まない。
- UTF-8本文のSHA-256、相対scope、mtime、summary、secret line除外件数を返す。
- 同一hashはunchanged、hash変更は新しいInstructionArtifact候補、欠落はunavailableとして通知し、旧観測を破壊しない。
- API key、token、password、secret、private key、authorizationの値をsummary、ログ、artifactに含めない。
- scannerは対象ファイルを作成・更新・削除しない。

## 回帰テスト

- `backend/tests/test_founder_graph_instruction_scanner.py::test_scanner_accepts_agents_and_skill_under_allowed_root`
- `backend/tests/test_founder_graph_instruction_scanner.py::test_scanner_rejects_outside_and_symlink_paths`
- `backend/tests/test_founder_graph_instruction_scanner.py::test_scanner_tracks_hash_change_and_missing_without_mutating_history`
- `backend/tests/test_founder_graph_instruction_scanner.py::test_secret_lines_are_excluded_from_summary_and_artifact`

## 完了判定

focused suite、全backend suite、`py_compile`、`git diff --check`がgreenで、差分500行以下の単一目的であること。
