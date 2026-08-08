export const LOCAL_GOOGLE_PRINCIPAL = Object.freeze({
  id: 'local-google-user', provider: 'google-local-mock', displayName: 'ローカル Google テスト利用者',
});

export function createLocalGoogleAuthAdapter({ profile = 'local', principal = LOCAL_GOOGLE_PRINCIPAL } = {}) {
  let current = null;
  return {
    profile,
    currentPrincipal: () => current,
    signIn: async () => {
      if (profile !== 'local' && profile !== 'test') throw new Error('外部認証は設定されていません。');
      current = principal;
      return current;
    },
    signOut: async () => { current = null; },
  };
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
