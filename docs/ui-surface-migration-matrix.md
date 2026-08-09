# UI surface migration matrix

| Surface | Owner | 第一PR状態 | 次の移行単位 | 禁止範囲 |
|---|---|---|---|---|
| Shared tokens | プロダクトUI・デザインシステム部 | 完了 | color/motion/a11y token拡張 | workflow/API |
| Shared primitives | プロダクトUI・デザインシステム部 | 完了 | Button/Card/Badge/Fieldの利用拡大 | 独自dialog/menuの追加 |
| Account sidebar | プロダクトUI・デザインシステム部 | 基盤接続 | WorkspaceShellの段階移行 | nav構造・auth/runtime |
| Plan selection | プロダクトUI・デザインシステム部 | 第一PR対象 | Model selectorとの共通化 | 課金・Pro実装 |
| Home | 会話体験・プロジェクト部 | 後続 | composer/canvas | workflow/API |
| Project | 会話体験・プロジェクト部 | 後続 | project surface | workflow/API |
| Knowledge | 会話体験・プロジェクト部 | 後続 | knowledge surface | workflow/API |

移行状態は `未着手 → 基盤接続 → 完了` の順で更新し、各PRは一つのsurface単位に限定する。
