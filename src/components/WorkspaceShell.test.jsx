// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { describe, expect, it } from 'vitest';

import { WorkspaceShell } from './WorkspaceShell';
import { LocalGoogleSignIn } from './LocalGoogleSignIn';
import { createLocalGoogleAuthAdapter } from '../auth/localAuthAdapter';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

function mount() {
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  act(() => root.render(<WorkspaceShell activePage="ideas" onSelect={() => {}}><h1>ページ</h1></WorkspaceShell>));
  return { container, cleanup: () => act(() => { root.unmount(); container.remove(); }) };
}

describe('WorkspaceShell', () => {
  it.each([
    ['desktop account area', false],
    ['390px mobile drawer account area', true],
  ])('restores the signed-in principal after remount in the %s', async (_label, mobile) => {
    const storage = { value: null, getItem() { return this.value; }, setItem(_key, value) { this.value = value; }, removeItem() { this.value = null; } };
    const container = document.createElement('div');
    document.body.append(container);
    let root = createRoot(container);

    function renderWithFreshAdapter(initialDrawerOpen = false) {
      const adapter = createLocalGoogleAuthAdapter({ storage });
      act(() => root.render(<WorkspaceShell activePage="ideas" onSelect={() => {}} initialDrawerOpen={initialDrawerOpen} accountContent={<LocalGoogleSignIn authAdapter={adapter} />}><h1>ページ</h1></WorkspaceShell>));
    }

    renderWithFreshAdapter();
    expect(container.textContent).toContain('確認中');
    if (mobile) {
      act(() => container.querySelector('.workspace-shell__mobile-trigger').click());
      expect(container.querySelector('.workspace-shell__sidebar').className).toContain('workspace-shell__sidebar--open');
    }
    await act(async () => Promise.resolve());
    expect(container.textContent).toContain('Googleで続ける');
    await act(async () => container.querySelector('.workspace-shell__account-auth button').click());
    expect(container.textContent).toContain('ローカル Google テスト利用者');

    act(() => root.unmount());
    root = createRoot(container);
    renderWithFreshAdapter(mobile);
    await act(async () => Promise.resolve());
    expect(container.textContent).toContain('ローカル Google テスト利用者');
    act(() => { root.unmount(); container.remove(); });
  });

  it('renders the vertical information architecture and account footer', () => {
    const { container, cleanup } = mount();
    expect(container.querySelector('[aria-label="ワークスペースサイドバー"]')).toBeTruthy();
    expect(container.querySelectorAll('.workspace-shell__nav-item')).toHaveLength(3);
    expect(container.querySelector('.workspace-shell__mobile-trigger').getAttribute('aria-controls')).toBe('workspace-sidebar');
    expect(container.querySelector('#workspace-sidebar')).toBeTruthy();
    expect(container.textContent).toContain('あなたの情報');
    expect(container.textContent).toContain('Free');
    cleanup();
  });

  it('collapses the sidebar and closes the mobile drawer with Escape', () => {
    const { container, cleanup } = mount();
    act(() => container.querySelector('.workspace-shell__collapse').click());
    expect(container.querySelector('.workspace-shell').className).toContain('workspace-shell--collapsed');
    act(() => container.querySelector('.workspace-shell__mobile-trigger').click());
    expect(container.querySelector('.workspace-shell__sidebar').className).toContain('workspace-shell__sidebar--open');
    act(() => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })));
    expect(container.querySelector('.workspace-shell__sidebar').className).not.toContain('workspace-shell__sidebar--open');
    cleanup();
  });
});
