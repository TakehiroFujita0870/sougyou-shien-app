// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import axe from 'axe-core';
import { afterEach, describe, expect, it } from 'vitest';

import { WorkspaceChatPage } from './WorkspaceChatPage';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const repository = (stored) => ({ load: async () => stored, save: async (next) => next });
const setTextareaValue = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;

async function mount(props = {}) {
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  await act(async () => root.render(<WorkspaceChatPage repository={repository()} currentPage="資料" {...props} />));
  return { container, unmount: () => act(() => { root.unmount(); container.remove(); }) };
}

afterEach(() => document.body.replaceChildren());

describe('WorkspaceChatPage', () => {
  it('has no axe violations in the local chat entry', async () => {
    const view = await mount();
    expect((await axe.run(view.container)).violations).toEqual([]);
    await view.unmount();
  });

  it('keeps space and project conversations separate', async () => {
    const view = await mount();
    const input = view.container.querySelector('textarea');
    await act(async () => { setTextareaValue.call(input, '設備保全の案です'); input.dispatchEvent(new Event('input', { bubbles: true })); view.container.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); });
    expect(view.container.textContent).toContain('設備保全の案です');
    await act(async () => Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent === 'プロジェクト会話').click());
    expect(view.container.textContent).not.toContain('設備保全の案です');
    expect(view.container.textContent).toContain('プロジェクト単位の会話');
    await view.unmount();
  });

  it('requires an explicit adoption before showing a project as created', async () => {
    const view = await mount();
    const input = view.container.querySelector('textarea');
    await act(async () => { setTextareaValue.call(input, '現場の記録を整理したい'); input.dispatchEvent(new Event('input', { bubbles: true })); view.container.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); });
    expect(view.container.textContent).not.toContain('プロジェクトとして採用しました');
    await act(async () => Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent === 'プロジェクトに採用して深掘り').click());
    expect(view.container.textContent).toContain('プロジェクトとして採用しました');
    await view.unmount();
  });

  it('does not overwrite a user draft when hydration resolves later', async () => {
    let resolve;
    const lateRepository = { load: () => new Promise((done) => { resolve = done; }), save: async (next) => next };
    const view = await mount({ repository: lateRepository });
    const input = view.container.querySelector('textarea');
    await act(async () => { setTextareaValue.call(input, 'いま書いた内容'); input.dispatchEvent(new Event('input', { bubbles: true })); resolve({ draft: '古い下書き', conversations: {} }); });
    expect(input.value).toBe('いま書いた内容');
    await view.unmount();
  });

  it('shows only fixed-space available knowledge without owner or grant controls', async () => {
    const view = await mount({ ownerId: 'ignored-by-chat', knowledge: [{ id: 'visible', name: '顧客メモ', kind: 'research', sourceId: 'r-1', locator: '段落 2' }, { id: 'removed', name: '削除済み資料', status: 'unavailable' }, { id: 'deleted', name: '削除伝播済み資料', state: 'deleted' }] });
    expect(view.container.textContent).toContain('research: r-1 · 段落 2');
    expect(view.container.textContent).not.toContain('削除済み資料');
    expect(view.container.textContent).not.toContain('削除伝播済み資料');
    expect(view.container.textContent).not.toContain('ignored-by-chat');
    expect(view.container.textContent).not.toContain('grant');
    await view.unmount();
  });
});
