import { useEffect, useRef, useState } from 'react';

import { createLocalGoogleAuthAdapter } from '../auth/localAuthAdapter';

export function LocalGoogleSignIn({ authAdapter }) {
  const adapterRef = useRef(authAdapter);
  if (!adapterRef.current) adapterRef.current = createLocalGoogleAuthAdapter();
  const adapter = adapterRef.current;
  const [principal, setPrincipal] = useState(() => adapter.currentPrincipal());
  const [status, setStatus] = useState(() => adapter.currentStatus());
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    adapter.hydrate().then((restored) => {
      if (!active) return;
      setPrincipal(restored);
      setStatus(adapter.currentStatus());
    });
    return () => { active = false; };
  }, [adapter]);

  async function signIn() {
    setError('');
    try { setPrincipal(await adapter.signIn()); setStatus(adapter.currentStatus()); } catch (exception) { setError(exception.message); }
  }

  async function signOut() {
    await adapter.signOut();
    setPrincipal(null);
    setStatus(adapter.currentStatus());
  }

  if (status === 'hydrating') return <span className="workspace-shell__account-status" aria-label="認証状態を確認中">確認中…</span>;
  if (status === 'error') return <span className="workspace-shell__account-status" role="alert">認証状態を読み込めません。再試行してください。</span>;
  if (principal) return <div className="workspace-shell__account-auth"><strong>{principal.displayName}</strong><button type="button" onClick={signOut}>サインアウト</button></div>;
  return <div className="workspace-shell__account-auth"><button type="button" onClick={signIn}>Googleで続ける</button>{error && <span role="alert">{error}</span>}</div>;
}
