// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { describe, expect, it } from 'vitest';

import { WorkspaceShell } from './WorkspaceShell';
import { LocalGoogleSignIn } from './LocalGoogleSignIn';
import { createLocalGoogleAuthAdapter } from '../auth/localAuthAdapter';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

function openAccount(container) {
  const trigger = container.querySelector('.workspace-shell__account-copy > button');
  act(() => trigger.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true, button: 0 })));
}

function mount() {
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  act(() => root.render(<WorkspaceShell activePage="ideas" onSelect={() => {}}><h1>ページ</h1></WorkspaceShell>));
  return { container, cleanup: () => act(() => { root.unmount(); container.remove(); }) };
}

describe('WorkspaceShell', () => {
  it('hydrates and restores a signed-in principal through the explicit account menu', async () => {
    const storage = { value: null, getItem() { return this.value; }, setItem(_key, value) { this.value = value; }, removeItem() { this.value = null; } };
    const container = document.createElement('div'); document.body.append(container); let root = createRoot(container);
    const render = () => act(() => root.render(<WorkspaceShell activePage="home" onSelect={() => {}} accountContent={<LocalGoogleSignIn authAdapter={createLocalGoogleAuthAdapter({ storage })} />}><h1>ページ</h1></WorkspaceShell>));
    render();
    openAccount(container);
    await act(async () => new Promise((resolve) => setTimeout(resolve, 50)));
    expect(document.body.textContent).toContain('Googleで続ける');
    await act(async () => document.querySelector('.workspace-shell__account-auth button').click());
    expect(document.body.textContent).toContain('ローカル Google テスト利用者');
    act(() => root.unmount()); root = createRoot(container); render(); openAccount(container);
    await act(async () => new Promise((resolve) => setTimeout(resolve, 50)));
    expect(document.querySelector('[role="menu"]')).toBeTruthy();
    const restoredAdapter = createLocalGoogleAuthAdapter({ storage });
    await expect(restoredAdapter.hydrate()).resolves.toEqual(expect.objectContaining({ id: 'local-google-user' }));
    act(() => { root.unmount(); container.remove(); });
  });
  it.each([
    ['desktop account area', false],
    ['390px mobile drawer account area', true],
  ])('restores the signed-in principal after remount in the %s', async (_label, mobile) => {
    const container = document.createElement('div');
    document.body.append(container);
    let root = createRoot(container);

    function renderWithFreshAdapter(initialDrawerOpen = false) {
      act(() => root.render(<WorkspaceShell activePage="home" onSelect={() => {}} initialDrawerOpen={initialDrawerOpen}><h1>ページ</h1></WorkspaceShell>));
    }

    renderWithFreshAdapter();
    if (mobile) {
      act(() => container.querySelector('.workspace-shell__mobile-trigger').click());
      expect(container.querySelector('.workspace-shell__sidebar').className).toContain('workspace-shell__sidebar--open');
    }
    act(() => root.unmount());
    root = createRoot(container);
    renderWithFreshAdapter(mobile);
    await act(async () => Promise.resolve());
    expect(container.textContent).toContain('タケヒロ');
    act(() => { root.unmount(); container.remove(); });
  });

  it('renders the vertical information architecture and account footer', () => {
    const { container, cleanup } = mount();
    expect(container.querySelector('[aria-label="ワークスペースサイドバー"]')).toBeTruthy();
    expect(container.querySelectorAll('.workspace-shell__nav-item')).toHaveLength(3);
    expect(container.querySelector('.workspace-shell__mobile-trigger').getAttribute('aria-controls')).toBe('workspace-sidebar');
    expect(container.querySelector('#workspace-sidebar')).toBeTruthy();
    expect(container.textContent).toContain('タケヒロ');
    expect(container.textContent).toContain('Free');
    const accountTrigger = container.querySelector('.workspace-shell__account-copy > button');
    expect(accountTrigger.textContent).toContain('⌄');
    expect(document.querySelector('[role="menu"]')).toBeNull();
    accountTrigger.focus();
    openAccount(container);
    expect(document.querySelector('[role="menu"]')).toBeTruthy();
    expect(document.body.textContent).toContain('あなたの情報');
    expect(document.body.textContent).toContain('プランと利用状況');
    expect(document.body.textContent).toContain('設定');
    expect(document.body.textContent).toContain('ヘルプ・ショートカット');
    expect(document.body.textContent).toContain('ログアウト');
    act(() => document.querySelector('[role="menu"]').dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })));
    expect(document.querySelector('[role="menu"]')).toBeNull();
    expect(document.activeElement).toBe(accountTrigger);
    cleanup();
  });

  it('keeps the three-surface sidebar and closes the mobile drawer with Escape', () => {
    const { container, cleanup } = mount();
    expect(container.querySelector('.workspace-shell__collapse')).toBeNull();
    act(() => container.querySelector('.workspace-shell__mobile-trigger').click());
    expect(container.querySelector('.workspace-shell__sidebar').className).toContain('workspace-shell__sidebar--open');
    act(() => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })));
    expect(container.querySelector('.workspace-shell__sidebar').className).not.toContain('workspace-shell__sidebar--open');
    cleanup();
  });
});
