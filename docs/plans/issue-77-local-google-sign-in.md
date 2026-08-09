# Issue #77 / PR #89 local Google sign-in mock 再計画

最終検証日: 2026-08-09

## 要望 / ゴール / 成功指標

要望: local Google mock sessionをversioned storageでF5復元し、hydrate前のsigned-out flashを防ぎ、破損値はfail-safeに扱い、stable adapterをGoogle account領域へ統合する。

ゴール: local/test profileだけで、desktopとmobileの同じWorkspaceShell account導線から、外部接続なしに復元・sign-in・sign-outできる。

成功指標: 有効session復元、hydrate中のsigned-out UI非表示、破損/旧version値の削除とsigned-out復帰、adapter差し替えによる状態リセットなし、外部OAuth surfaceなしを自動テストで確認する。

## ユーザーストーリーと受け入れ条件

### US-1
As a local/test user, I want my mock Google session restored after F5, so that local work continues without external authentication.

Given: versioned local storage contains the adapter's fixture principal.
When: the account component hydrates.
Then: the fixture principal is shown in the WorkspaceShell account area on desktop and mobile.

### US-2
As a signed-out user, I want hydration to complete before account actions appear, so that stale signed-out UI is not flashed.

Given: adapter hydration is pending.
When: the account component renders.
Then: only a hydration status is shown and sign-in controls are absent.

### US-3
As a local/test user, I want corrupt or obsolete storage to fail safe, so that I can continue signed out.

Given: storage contains malformed, mismatched, or obsolete session data.
When: hydration runs.
Then: the value is removed, the adapter becomes ready and signed out, and sign-in remains available.

### US-4
As a local/test user, I want one stable adapter instance, so that rerenders do not change the authenticated principal.

Given: the account component is rerendered with a new adapter prop.
When: the component continues its lifecycle.
Then: the initially mounted adapter remains the source of auth state.

### US-5
As a Kadode user on any supported surface, I want Google sign-in in the account area, so that mobile uses the same authentication boundary.

Given: the WorkspaceShell is rendered at any viewport.
When: the account area is opened.
Then: the same local mock sign-in component is available without redirect, network, token, or email sending.

## 3 surface IA / context boundary

- T-IA-03 (context/privacy)との接続境界はAuthAdapterが返すfixture principalとowner-scoped local stateの間に置く。認証principal以外のcontext、会話内容、個人情報はこのPRへ渡さない。
- 3 surface IA（Home / Project / Knowledge）は共通のWorkspaceShell account領域を利用し、各surface固有の認証UIや状態を持たない。mobileはdrawer内の同一account領域を使う。
- T-IA-03の実session、実RLS、実外部providerへの接続は別Issue/PRの契約とし、本PRではlocal adapter境界を越えない。

## スコープ外

- Google OAuth client、Supabase provider、redirect URL、実email/token送信、#31の実RLS接続。
- 3 surface各ページへの個別auth state、context/privacy情報の永続化、外部network。

## タスク

| ID | 成果物 | 完了判定（検査:） | 不確実性 |
|---|---|---|---|
| T-77-1 | versioned local adapterのhydrate/sign-in/sign-out | 検査: `npm run test -- --run src/auth/localAuthAdapter.test.js` | 既知 |
| T-77-2 | hydrate gateとstable adapterのaccount UI | 検査: `npm run test -- --run src/components/LocalGoogleSignIn.test.jsx src/App.test.jsx` | 既知 |
| T-77-3 | 3 surface IA / T-IA-03境界の計画記録 | 検査: 計画文書の境界節と禁止事項をレビュー | 既知 |

## ADR

- **versioned browser storage**: versionとprincipal idを検証して復元し、破損/旧versionは削除してready/signed-outへ戻す。React stateのみはF5復元できないため却下。
- **mount-time stable adapter**: 初回mountのadapterをrefへ保持する。毎renderでadapterを作り直す方式はhydrateとprincipalを失うため却下。
- **WorkspaceShell account boundary**: desktop/mobile共通のaccountContentへ統合する。surfaceごとのauth UIはT-IA-03の境界を複製するため却下。

## 変更履歴

| 日時 | 変更 | 理由 | 影響タスク |
|---|---|---|---|
| 2026-08-09 | PR #89の再計画。fail-safe、stable adapter、共通account導線、3 surface IA/T-IA-03境界を明文化 | Issue #77の受入条件を観測可能に統合 | T-77-1〜3 |
