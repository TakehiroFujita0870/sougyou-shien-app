// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { createLocalGoogleAuthAdapter } from '../auth/localAuthAdapter';
import { LocalGoogleSignIn } from './LocalGoogleSignIn';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

describe('LocalGoogleSignIn', () => {
  it('has no external link, form action, or redirect surface', () => {
    const html = renderToStaticMarkup(<LocalGoogleSignIn />);

    expect(html).toContain('Googleで続ける（local mock）');
    expect(html).not.toContain('href=');
    expect(html).not.toContain('<form');
    expect(html).not.toContain('action=');
    expect(html).not.toContain('redirect');
    expect(html).not.toContain('window.location');
  });

  it('retains the same supplied adapter after rerender', async () => {
    const adapter = createLocalGoogleAuthAdapter();
    const container = document.createElement('div');
    document.body.append(container);
    const root = createRoot(container);

    await act(async () => root.render(<LocalGoogleSignIn authAdapter={adapter} />));
    await act(async () => container.querySelector('button').click());
    await act(async () => root.render(<LocalGoogleSignIn authAdapter={createLocalGoogleAuthAdapter()} />));

    expect(container.textContent).toContain('local mock でサインイン中');
    expect(adapter.currentPrincipal()).not.toBeNull();
    await act(() => root.unmount());
    container.remove();
  });
});
