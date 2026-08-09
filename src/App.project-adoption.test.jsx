// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it } from 'vitest';

import { App } from './App';
import { createAdoptedProjectRepository } from './components/adoptedProjectRepository';
import { EMPTY_PROFILE } from './components/UserProfileInterview';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const adoptedCandidate = {
  id: 'candidate-adopted',
  title: '保全記録の検索支援',
  fact: '現場で履歴検索に時間がかかる',
  inference: '検索可能な記録の事業性を深掘りする',
  reason: '会話で採用',
  status: 'adopted',
};

function createStorage() {
  const values = new Map();
  return { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, String(value)) };
}

function completedProfileRepository() {
  return { load: async () => ({ values: EMPTY_PROFILE, step: 5, status: 'completed', error: '' }), save: async (value) => value };
}

async function mount({ projectRepository }) {
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  await act(async () => { root.render(<App adoptedProjectRepository={projectRepository} profileRepository={completedProfileRepository()} />); });
  await act(async () => Promise.resolve());
  return { container, unmount: () => act(() => { root.unmount(); container.remove(); }) };
}

function selectProject(container) {
  const button = [...container.querySelectorAll('.workspace-shell__nav-item')].find((item) => item.textContent === 'Project');
  button.click();
}

afterEach(() => document.body.replaceChildren());

describe('adopted project hydration', () => {
  it('restores an adopted Home candidate in Project after a fresh App mount', async () => {
    const storage = createStorage();
    const firstRepository = createAdoptedProjectRepository({ storage });
    await firstRepository.saveAdopted(adoptedCandidate);

    const first = await mount({ projectRepository: createAdoptedProjectRepository({ storage }) });
    await act(async () => selectProject(first.container));
    expect(first.container.textContent).toContain(adoptedCandidate.title);
    expect(first.container.textContent).toContain(adoptedCandidate.fact);
    expect(first.container.textContent).toContain(adoptedCandidate.inference);
    await first.unmount();

    const reloaded = await mount({ projectRepository: createAdoptedProjectRepository({ storage }) });
    await act(async () => selectProject(reloaded.container));
    expect(reloaded.container.textContent).toContain(adoptedCandidate.title);
    expect(reloaded.container.textContent).toContain(adoptedCandidate.reason);
    await reloaded.unmount();
  });
});
