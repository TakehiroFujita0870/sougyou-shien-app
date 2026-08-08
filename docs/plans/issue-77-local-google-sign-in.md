# Issue #77 local Google sign-in mock 計画

## 受け入れ条件

- Given local/test profile, When local mockを選ぶ, Then fixture principalだけを表示し外部OAuth・redirect・送信を行わない。
- Given owner Aのlocal state, When adapter由来のprincipal Bを使う, Then Aのstateを返さない。
- Given production profile, When sign-inする, Then unconfigured errorでfail closedする。

## スコープ外

Google OAuth client、Supabase provider、redirect URL、実email/token送信、#31の実RLS接続。

## ADR

ownerはUI入力ではなくAuthAdapterが返すprincipalからのみ確定する。#31で検証済みsessionと`auth.uid() = owner_id`へ移行し、実DBのA/B隔離を検証する。
