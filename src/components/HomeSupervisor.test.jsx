// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { describe, expect, it, vi } from 'vitest';
import { HomeSupervisor, proposeHomeAction } from './HomeSupervisor';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

describe('Home supervisor', () => {
  it('uses only a safe snapshot and never includes raw, token, or secret input', () => {
    const proposal = proposeHomeAction('プロジェクトを確認');
    expect(JSON.stringify(proposal)).not.toMatch(/raw|token|secret/i);
  });
  it('requires a visible confirmation before persisting a proposal as confirmed and never fetches', async () => {
    const container = document.createElement('div'); document.body.append(container); const root = createRoot(container); const stored = { messages: [], proposals: [] }; const saves = [];
    const repository = { load: async () => stored, save: async (value) => { saves.push(value); Object.assign(stored, value); return value; } }; const fetchSpy = vi.spyOn(globalThis, 'fetch');
    await act(async () => root.render(<HomeSupervisor repository={repository} />)); await act(async () => {});
    const input = container.querySelector('#home-supervisor-message'); const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
    await act(async () => { setter.call(input, 'プロジェクトを一覧で確認'); input.dispatchEvent(new Event('input', { bubbles: true })); container.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); });
    expect(stored.proposals[0].confirmed).toBe(false); expect(container.textContent).toContain('事実:'); expect(container.textContent).toContain('推論:'); expect(container.textContent).toContain('操作:');
    await act(async () => container.querySelector('button[type="button"]').click()); expect(stored.proposals[0].confirmed).toBe(true); expect(fetchSpy).not.toHaveBeenCalled();
    await act(() => root.unmount()); const remount = createRoot(container); await act(async () => remount.render(<HomeSupervisor repository={repository} />)); await act(async () => {}); expect(container.textContent).toContain('確認済み'); await act(() => remount.unmount()); container.remove(); fetchSpy.mockRestore();
  });
});
