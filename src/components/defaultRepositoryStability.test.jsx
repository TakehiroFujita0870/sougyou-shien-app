// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { IdeaCandidateWorkspace } from './IdeaCandidateWorkspace';
import { UserProfileInterview } from './UserProfileInterview';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

async function mount(element) {
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  await act(async () => root.render(element));
  return () => act(() => { root.unmount(); container.remove(); });
}

describe('default browser repositories', () => {
  it('loads the profile once after a normal mount', async () => {
    const getItem = vi.spyOn(localStorage, 'getItem');

    const unmount = await mount(<UserProfileInterview onClose={vi.fn()} onComplete={vi.fn()} />);

    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(getItem).toHaveBeenCalledTimes(1);
    await unmount();
  });

  it('loads idea candidates once after a normal mount', async () => {
    const getItem = vi.spyOn(localStorage, 'getItem');

    const unmount = await mount(<IdeaCandidateWorkspace />);

    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(getItem).toHaveBeenCalledTimes(1);
    await unmount();
  });
});
