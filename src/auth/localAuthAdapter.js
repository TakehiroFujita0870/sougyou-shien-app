export const LOCAL_GOOGLE_PRINCIPAL = Object.freeze({
  id: 'local-google-user',
  provider: 'google-local-mock',
  displayName: 'ローカル Google テスト利用者',
});

export const LOCAL_AUTH_STORAGE_VERSION = 1;

function safeStorage(storage) {
  return storage ?? null;
}

export function createLocalGoogleAuthAdapter({
  profile = 'local',
  principal = LOCAL_GOOGLE_PRINCIPAL,
  storage = globalThis.localStorage,
  storageKey = 'kadode:local-auth',
} = {}) {
  let current = null;
  let status = 'hydrating';
  const store = safeStorage(storage);

  function currentPrincipal() {
    return current;
  }

  function currentStatus() {
    return status;
  }

  async function hydrate() {
    if (!store) {
      status = 'ready';
      return null;
    }
    try {
      const raw = store.getItem(storageKey);
      if (!raw) {
        status = 'ready';
        return null;
      }
      const saved = JSON.parse(raw);
      if (
        saved?.version !== LOCAL_AUTH_STORAGE_VERSION
        || saved?.principal?.id !== principal.id
        || saved?.principal?.provider !== principal.provider
      ) {
        try { store.removeItem(storageKey); } catch { /* fail-safe cleanup */ }
        current = null;
        status = 'ready';
        return null;
      }
      current = principal;
      status = 'ready';
      return current;
    } catch {
      try { store.removeItem(storageKey); } catch { /* fail-safe cleanup */ }
      current = null;
      status = 'ready';
      return null;
    }
  }

  async function signIn() {
    if (profile !== 'local' && profile !== 'test') {
      throw new Error('外部認証は設定されていません。');
    }
    try {
      if (!store) throw new Error('storage unavailable');
      store.setItem(storageKey, JSON.stringify({ version: LOCAL_AUTH_STORAGE_VERSION, principal }));
    } catch {
      current = null;
      status = 'error';
      throw new Error('認証状態を端末に保存できません。');
    }
    current = principal;
    status = 'ready';
    return current;
  }

  async function signOut() {
    current = null;
    try { store?.removeItem(storageKey); } catch { status = 'error'; }
    status = 'ready';
  }

  return { profile, currentPrincipal, currentStatus, hydrate, signIn, signOut };
}

export function createOwnerScopedLocalState() {
  const values = new Map();
  return {
    read(principal) { return values.get(principal?.id) ?? null; },
    write(principal, value) {
      if (!principal?.id) throw new Error('認証が必要です。');
      values.set(principal.id, value);
    },
  };
}
