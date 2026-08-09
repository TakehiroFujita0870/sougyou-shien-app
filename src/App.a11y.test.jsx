// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import axe from 'axe-core';
import { describe, expect, it } from 'vitest';

import { App } from './App';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const profileRepository = { load: async () => null, save: async (profile) => profile };

async function mount() {
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  await act(async () => root.render(<App profileRepository={profileRepository} />));
  return { container, unmount: () => act(() => { root.unmount(); container.remove(); }) };
}

describe('App keyboard and accessibility quality', () => {
  it('has no axe violations in the primary desktop UI', async () => {
    const { container, unmount } = await mount();

    const results = await axe.run(container);

    expect(results.violations).toEqual([]);
    await unmount();
  });

  it('moves workspaces with the documented PC shortcut and ignores text entry', async () => {
    const { container, unmount } = await mount();

    await act(() => window.dispatchEvent(new KeyboardEvent('keydown', { key: '2', altKey: true, shiftKey: true, bubbles: true })));
    expect([...container.querySelectorAll('button')].find((button) => button.textContent === 'Project')?.getAttribute('aria-current')).toBe('page');

    const input = container.querySelector('textarea');
    await act(() => input.dispatchEvent(new KeyboardEvent('keydown', { key: '3', altKey: true, shiftKey: true, bubbles: true })));
    expect([...container.querySelectorAll('button')].find((button) => button.textContent === 'Project')?.getAttribute('aria-current')).toBe('page');
    await unmount();
  });

  it('closes the profile dialog with Escape and preserves tokenized visible focus styles and 44px navigation targets', async () => {
    const { container, unmount } = await mount();
    const dialog = container.querySelector('[role="dialog"]');

    await act(() => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })));
    expect(dialog.isConnected).toBe(false);

    const navigation = container.querySelector('nav[aria-label="主要ページ"]');
    expect([...navigation.querySelectorAll('button')].map((button) => button.textContent)).toEqual(['Home', 'Project', 'Knowledge']);
    expect(navigation.textContent).not.toContain('AI広報');
    expect(navigation.querySelector('button').className).toContain('workspace-shell__nav-item');
    expect(container.querySelector('main').className).toContain('kadode-shell');
    expect(container.querySelector('.workspace-shell__nav-item').className).toContain('workspace-shell__nav-item');
    await unmount();
  });

  it('constrains the mobile shell and profile dialog instead of expanding the page width', async () => {
    const { container, unmount } = await mount();
    await act(async () => Promise.resolve());

    const dialog = container.querySelector('[role="dialog"]');
    const panel = dialog.querySelector('section');
    const header = container.querySelector('header > div');
    const navigation = container.querySelector('nav[aria-label="主要ページ"]');

    expect(dialog.className).toContain('grid-cols-[minmax(0,1fr)]');
    expect(panel.className).toContain('min-w-0');
    expect(panel.className).toContain('max-w-full');
    expect(header.className).toContain('min-w-0');
    expect(navigation.className).toContain('min-w-0');
    expect(container.querySelector('main').className).toContain('kadode-shell');
    await unmount();
  });
});
