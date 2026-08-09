// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { describe, expect, it, vi } from 'vitest';
import fixture from '../fixtures/knowledge-admin-demo.json';
import { KnowledgeSurface } from './KnowledgeSurface';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

async function mount(props = {}) {
  const container = document.createElement('div'); document.body.append(container);
  const root = createRoot(container);
  await act(async () => root.render(<KnowledgeSurface fixture={fixture} {...props} />));
  return { container, unmount: () => act(() => { root.unmount(); container.remove(); }) };
}

describe('KnowledgeSurface', () => {
  it('shows files, locators, project context, and decision history without PII or external fetching', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    const { container, unmount } = await mount();
    expect(container.textContent).toContain('顧客ヒアリング要約');
    expect(container.textContent).toContain('資料 / 顧客ヒアリング要約 / 1頁');
    expect(container.textContent).toContain('小規模な検証から始める');
    expect(container.textContent).not.toMatch(/email|phone|address|ownerId|spaceId/i);
    expect(fetchSpy).not.toHaveBeenCalled();
    await unmount(); fetchSpy.mockRestore();
  });

  it('requires an explicit confirmation before removal and calls the local handler only on confirm', async () => {
    const onRemoveAsset = vi.fn(); const { container, unmount } = await mount({ onRemoveAsset });
    await act(async () => [...container.querySelectorAll('button')].find((button) => button.textContent === '削除').click());
    expect(document.querySelector('[role="dialog"]')).toBeTruthy(); expect(onRemoveAsset).not.toHaveBeenCalled();
    await act(async () => [...document.querySelectorAll('button')].find((button) => button.textContent === '削除を確定').click());
    expect(onRemoveAsset).toHaveBeenCalledWith('demo-document-001');
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    await unmount();
  });

  it('keeps an always-visible composer and sends through the local callback', async () => {
    const onSend = vi.fn(); const { container, unmount } = await mount({ onSend });
    const input = container.querySelector('#knowledge-composer');
    const setValue = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
    await act(async () => { setValue.call(input, '根拠を比べたい'); input.dispatchEvent(new Event('input', { bubbles: true })); input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })); });
    expect(onSend).toHaveBeenCalledWith('根拠を比べたい');
    await unmount();
  });

  it('shares the compact model and assist controls without exposing a persistent keyboard hint', async () => {
    const onModelChange = vi.fn();
    const models = [{ logicalKey: 'gpt-5.6-terra', displayName: 'GPT-5.6 Terra' }, { logicalKey: 'claude-sonnet-5', displayName: 'Claude Sonnet 5' }];
    const { container, unmount } = await mount({ models, modelKey: 'gpt-5.6-terra', onModelChange });
    expect(container.textContent).not.toContain('Enterで送信');
    expect(container.querySelector('[aria-label="Knowledgeの質問を送信"]')).toBeTruthy();
    await act(async () => container.querySelector('[data-testid="knowledge-assist"]').click());
    expect(container.querySelector('#knowledge-composer').value).toContain('過去の判断');
    const trigger = container.querySelector('[aria-label="モデル: GPT-5.6 Terra"]');
    await act(async () => trigger.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true, button: 0 })));
    const option = [...document.querySelectorAll('[role="menuitem"]')].find((item) => item.textContent.includes('Claude Sonnet 5'));
    await act(async () => option.click());
    expect(onModelChange).toHaveBeenCalledWith('claude-sonnet-5');
    await unmount();
  });
});
