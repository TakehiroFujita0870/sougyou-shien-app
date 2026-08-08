import { describe, expect, it } from 'vitest';

import { createLocalGoogleAuthAdapter, createOwnerScopedLocalState } from './localAuthAdapter';

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

  it('fails safe and reports an explicit error for corrupt storage', async () => {
    const adapter = createLocalGoogleAuthAdapter({ storage: storageFixture('{broken') });
    await expect(adapter.hydrate()).resolves.toBeNull();
    expect(adapter.currentStatus()).toBe('error');
    expect(adapter.currentPrincipal()).toBeNull();
  });

  it('fails closed outside local profiles and isolates owner state', async () => {
    await expect(createLocalGoogleAuthAdapter({ profile: 'production' }).signIn()).rejects.toThrow('設定');
    const state = createOwnerScopedLocalState();
    state.write({ id: 'a' }, 'A');
    expect(state.read({ id: 'b' })).toBeNull();
  });
});
