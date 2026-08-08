// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { App } from './App';
import { EMPTY_PROFILE } from './components/UserProfileInterview';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const completed = { values: { ...EMPTY_PROFILE, experience: '営業経験' }, step: 5, status: 'completed', error: '' };
const interrupted = { values: { ...EMPTY_PROFILE, experience: '保存済みの回答' }, step: 0, status: 'in_progress', error: '' };

async function mount(repository) {
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  await act(async () => root.render(<App profileRepository={repository} />));
  return {
    container,
    rerender: () => act(async () => root.render(<App profileRepository={repository} />)),
    unmount: () => act(() => { root.unmount(); container.remove(); }),
  };
}

afterEach(() => document.body.replaceChildren());

describe('profile hydration at the application boundary', () => {
  it('keeps a completed profile closed after reload and opens saved values only on request', async () => {
    const repository = { load: vi.fn().mockResolvedValue(completed), save: vi.fn() };
    const view = await mount(repository);

    expect(repository.load).toHaveBeenCalledTimes(1);
    expect(view.container.querySelector('[role="dialog"]')).toBeNull();
    expect(view.container.textContent).toContain('あなたの情報を更新');

    await act(async () => view.container.querySelector('.kadode-profile-button').click());
    expect(view.container.textContent).toContain('営業経験');

    await view.rerender();
    expect(repository.load).toHaveBeenCalledTimes(1);
    await view.unmount();
  });

  it.each([
    ['empty', null, ''],
    ['interrupted', interrupted, '保存済みの回答'],
  ])('opens the interview after a successful %s load', async (_label, profile, expectedValue) => {
    const view = await mount({ load: vi.fn().mockResolvedValue(profile), save: vi.fn() });

    expect(view.container.querySelector('[role="dialog"]')).not.toBeNull();
    expect(view.container.querySelector('[role="dialog"] textarea')?.value).toBe(expectedValue);
    await view.unmount();
  });

  it('blocks editing after load failure and recovers through retry', async () => {
    const repository = { load: vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(completed), save: vi.fn() };
    const view = await mount(repository);

    expect(view.container.textContent).toContain('読み込めませんでした');
    expect(view.container.querySelector('[role="dialog"] textarea')).toBeNull();
    expect(repository.save).not.toHaveBeenCalled();

    await act(async () => Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent === '再試行').click());
    expect(repository.load).toHaveBeenCalledTimes(2);
    expect(view.container.querySelector('[role="dialog"]')).toBeNull();
    expect(view.container.textContent).toContain('あなたの情報を更新');
    await view.unmount();
  });
});
