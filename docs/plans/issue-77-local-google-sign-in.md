# Issue #77 local Google sign-in mock 計画

## 受け入れ条件

- Given local/test profile, When local mockを選ぶ, Then fixture principalだけを表示し外部OAuth・redirect・送信を行わない。
- Given owner Aのlocal state, When adapter由来のprincipal Bを使う, Then Aのstateを返さない。
- Given production profile, When sign-inする, Then unconfigured errorでfail closedする。

## スコープ外

Google OAuth client、Supabase provider、redirect URL、実email/token送信、#31の実RLS接続。

## ADR

ownerはUI入力ではなくAuthAdapterが返すprincipalからのみ確定する。#31で検証済みsessionと`auth.uid() = owner_id`へ移行し、実DBのA/B隔離を検証する。

## 保守性ゲート

1. 既存の`createBrowserProfileRepository`とrepository propsを再利用できるか確認したが、認証principalのversioned hydrate・fail-closed状態・provider境界を持たないため直接共有しない。
2. Reactの`useRef`/`useEffect`、ブラウザ標準のStorage API、既存Tailwind/CSS tokenを採用した。新規依存や別styled UI基盤は追加しない。
3. 認証ライブラリは本Issueのlocal/fake境界に不要で、Supabase導入は#31のCEO決裁後に専用PRで評価する。
4. 独自adapterの保守責任はKadode担当部が持つ。#31で検証済みsessionへ移行できた時点、または実接続の契約が確定した時点でlocal adapterを削除・置換する。
