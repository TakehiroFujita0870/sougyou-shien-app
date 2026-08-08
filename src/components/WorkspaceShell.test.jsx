// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { describe, expect, it } from 'vitest';

import { WorkspaceShell } from './WorkspaceShell';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

function mount() {
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  act(() => root.render(<WorkspaceShell activePage="ideas" onSelect={() => {}}><h1>ページ</h1></WorkspaceShell>));
  return { container, cleanup: () => act(() => { root.unmount(); container.remove(); }) };
}

describe('WorkspaceShell', () => {
  it('renders the vertical information architecture and account footer', () => {
    const { container, cleanup } = mount();
    expect(container.querySelector('[aria-label="ワークスペースサイドバー"]')).toBeTruthy();
    expect(container.querySelectorAll('.workspace-shell__nav-item')).toHaveLength(6);
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
