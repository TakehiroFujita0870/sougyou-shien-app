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
  it('keeps the account trigger outside the independently scrollable recent list and exposes all recent items in a dialog', async () => {
    const entries = Array.from({ length: 11 }, (_, index) => ({ id: `thread-${index}`, title: `会話 ${index}` }));
    const container = document.createElement('div'); document.body.append(container);
    const root = createRoot(container);
    act(() => root.render(<WorkspaceShell activePage="home" onSelect={() => {}} portfolio={{ home: entries }}><div className="min-h-[2000px]">長い本文</div></WorkspaceShell>));
    expect(container.querySelector('.workspace-shell__sidebar').className).toContain('workspace-shell__sidebar');
    expect(container.querySelector('[aria-label="最近の項目"]').className).toContain('overflow-y-auto');
    expect(container.querySelector('.workspace-shell__account')).toBeTruthy();
    expect(container.textContent).toContain('すべて表示');
    act(() => [...container.querySelectorAll('button')].find((button) => button.textContent === 'すべて表示').click());
    expect(document.body.textContent).toContain('ホームの履歴');
    expect(document.querySelector('[aria-label="すべての履歴"]')).toBeTruthy();
    act(() => { root.unmount(); container.remove(); });
  });

  it('shows five Knowledge recents with an accessible unread dot and keeps the rest in all-items', () => {
    const entries = Array.from({ length: 6 }, (_, index) => ({ id: `knowledge-${index}`, title: `資料 ${index}`, unread: index === 0 }));
    const container = document.createElement('div'); document.body.append(container);
    const root = createRoot(container);
    act(() => root.render(<WorkspaceShell activePage="knowledge" onSelect={() => {}} portfolio={{ knowledge: entries }}><h1>Knowledge</h1></WorkspaceShell>));
    expect(container.querySelector('[aria-label="最近の項目"]').textContent).not.toContain('資料 5');
    expect(container.querySelector('[aria-label="新着"]')).toBeTruthy();
    expect([...container.querySelectorAll('button')].some((button) => button.textContent === 'すべて表示')).toBe(true);
    act(() => { root.unmount(); container.remove(); });
  });

  it('disables archive while persistence is pending and keeps the item when it fails', async () => {
    let resolveArchive;
    const pending = new Promise((resolve) => { resolveArchive = resolve; });
    const container = document.createElement('div'); document.body.append(container);
    const root = createRoot(container);
    act(() => root.render(<WorkspaceShell activePage="home" onSelect={() => {}} portfolio={{ home: [{ id: 'home:1', title: '保存中の会話' }] }} onArchive={() => pending}><h1>Home</h1></WorkspaceShell>));
    const archive = container.querySelector('[aria-label="保存中の会話をアーカイブ"]');
    act(() => archive.click());
    expect(archive.disabled).toBe(true);
    expect(archive.textContent).toBe('処理中…');
    await act(async () => { resolveArchive(false); await pending; });
    expect(container.textContent).toContain('保存中の会話');
    expect(archive.disabled).toBe(false);
    act(() => { root.unmount(); container.remove(); });
  });

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

  it('renders the vertical information architecture and account footer', async () => {
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
    expect([...document.querySelectorAll('[role="menuitem"]')].map((item) => item.textContent)).toEqual([
      'プロフィールを編集',
      'プランと利用状況',
      '設定',
      'ヘルプ・ショートカット',
      'ログアウト',
    ]);
    await act(async () => {
      document.querySelector('[role="menu"]').dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
      await Promise.resolve();
    });
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
