// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

import { createLocalGoogleAuthAdapter } from '../auth/localAuthAdapter';
import { LocalGoogleSignIn } from './LocalGoogleSignIn';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

describe('LocalGoogleSignIn', () => {
  it('has no external link, form action, or redirect surface', () => {
    const html = renderToStaticMarkup(<LocalGoogleSignIn />);

    expect(html).toContain('確認中');
    expect(html).not.toContain('href=');
    expect(html).not.toContain('<form');
    expect(html).not.toContain('action=');
    expect(html).not.toContain('redirect');
    expect(html).not.toContain('window.location');
  });

  it('does not flash signed-out UI before hydration completes', async () => {
    const pending = new Promise(() => {});
    const adapter = { currentPrincipal: () => null, currentStatus: () => 'hydrating', hydrate: () => pending, signIn: vi.fn(), signOut: vi.fn() };
    const html = renderToStaticMarkup(<LocalGoogleSignIn authAdapter={adapter} />);
    expect(html).toContain('確認中');
    expect(html).not.toContain('Googleで続ける');
  });

  it('retains the same supplied adapter after rerender', async () => {
    const adapter = createLocalGoogleAuthAdapter();
    const container = document.createElement('div');
    document.body.append(container);
    const root = createRoot(container);

    await act(async () => root.render(<LocalGoogleSignIn authAdapter={adapter} />));
    await act(async () => container.querySelector('button').click());
    await act(async () => root.render(<LocalGoogleSignIn authAdapter={createLocalGoogleAuthAdapter()} />));

    expect(container.textContent).toContain('ローカル Google テスト利用者');
    expect(adapter.currentPrincipal()).not.toBeNull();
    await act(() => root.unmount());
    container.remove();
  });
});
