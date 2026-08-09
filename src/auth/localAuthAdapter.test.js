import { describe, expect, it } from 'vitest';

import { createLocalGoogleAuthAdapter, createOwnerScopedLocalState, LOCAL_AUTH_STORAGE_VERSION } from './localAuthAdapter';

function storageFixture(initial = null) {
  let value = initial;
  return { getItem: () => value, setItem: (_, next) => { value = next; }, removeItem: () => { value = null; } };
}

describe('local Google auth adapter', () => {
  it('restores a versioned local session after refresh', async () => {
    const storage = storageFixture();
    const first = createLocalGoogleAuthAdapter({ storage });
    await first.signIn();
    const second = createLocalGoogleAuthAdapter({ storage });
    expect(second.currentPrincipal()).toBeNull();
    await expect(second.hydrate()).resolves.toMatchObject({ id: 'local-google-user' });
  });

  it('fails safe and returns ready signed-out for corrupt storage', async () => {
    const adapter = createLocalGoogleAuthAdapter({ storage: storageFixture('{broken') });
    await expect(adapter.hydrate()).resolves.toBeNull();
    expect(adapter.currentStatus()).toBe('ready');
    expect(adapter.currentPrincipal()).toBeNull();
  });

  it.each([
    ['obsolete version', JSON.stringify({ version: LOCAL_AUTH_STORAGE_VERSION - 1, principal: { id: 'local-google-user', provider: 'google-local-mock' } })],
    ['wrong provider', JSON.stringify({ version: LOCAL_AUTH_STORAGE_VERSION, principal: { id: 'local-google-user', provider: 'external-google' } })],
  ])('fails safe for %s', async (_label, value) => {
    const adapter = createLocalGoogleAuthAdapter({ storage: storageFixture(value) });
    await expect(adapter.hydrate()).resolves.toBeNull();
    expect(adapter.currentStatus()).toBe('ready');
    expect(adapter.currentPrincipal()).toBeNull();
  });

  it('fails closed when local storage is unavailable', async () => {
    const adapter = createLocalGoogleAuthAdapter({ storage: null });
    await expect(adapter.signIn()).rejects.toThrow();
    expect(adapter.currentPrincipal()).toBeNull();
  });

  it('fails closed when storage cannot persist a sign-in', async () => {
    const storage = { getItem: () => null, setItem: () => { throw new Error('quota'); }, removeItem: () => {} };
    const adapter = createLocalGoogleAuthAdapter({ storage });
    await expect(adapter.signIn()).rejects.toThrow('保存できません');
    expect(adapter.currentPrincipal()).toBeNull();
    expect(adapter.currentStatus()).toBe('error');
  });

  it('fails closed outside local profiles and isolates owner state', async () => {
    await expect(createLocalGoogleAuthAdapter({ profile: 'production' }).signIn()).rejects.toThrow('設定');
    const state = createOwnerScopedLocalState();
    state.write({ id: 'a' }, 'A');
    expect(state.read({ id: 'b' })).toBeNull();
  });
});
