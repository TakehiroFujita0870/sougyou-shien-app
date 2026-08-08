// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { IdeaCandidateWorkspace } from './IdeaCandidateWorkspace';
import { UserProfileInterview } from './UserProfileInterview';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

beforeEach(() => {
  const values = new Map();
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, String(value)), clear: () => values.clear() } });
});

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

async function mount(element) {
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  await act(async () => root.render(element));
  return {
    rerender: (next) => act(async () => root.render(next)),
    unmount: () => act(() => { root.unmount(); container.remove(); }),
  };
}

function callsFor(getItem, key) {
  return getItem.mock.calls.filter(([requestedKey]) => requestedKey === key);
}

describe('default browser repositories', () => {
  it('loads the profile once after a normal mount', async () => {
    const getItem = vi.spyOn(localStorage, 'getItem');

    const view = await mount(<UserProfileInterview onClose={vi.fn()} onComplete={vi.fn()} />);

    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(callsFor(getItem, 'kadode:user-profile')).toHaveLength(1);
    await view.rerender(<UserProfileInterview onClose={vi.fn()} onComplete={vi.fn()} />);
    expect(callsFor(getItem, 'kadode:user-profile')).toHaveLength(1);
    await view.unmount();
  });

  it('loads each idea repository once and does not reload them on render', async () => {
    const getItem = vi.spyOn(localStorage, 'getItem');

    const view = await mount(<IdeaCandidateWorkspace />);

    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(callsFor(getItem, 'kadode:idea-candidates')).toHaveLength(1);
    expect(callsFor(getItem, 'kadode:idea-conversation')).toHaveLength(1);
    expect(callsFor(getItem, 'kadode:idea-input-draft')).toHaveLength(1);
    await view.rerender(<IdeaCandidateWorkspace />);
    expect(callsFor(getItem, 'kadode:idea-candidates')).toHaveLength(1);
    expect(callsFor(getItem, 'kadode:idea-conversation')).toHaveLength(1);
    expect(callsFor(getItem, 'kadode:idea-input-draft')).toHaveLength(1);
    await view.unmount();
  });
});
