// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it } from 'vitest';

import { App } from './App';
import { createAdoptedProjectRepository } from './components/adoptedProjectRepository';
import { createSidebarPortfolioRepository } from './components/sidebarPortfolioRepository';
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

function deferred() {
  let resolve;
  const promise = new Promise((resolvePromise) => { resolve = resolvePromise; });
  return { promise, resolve };
}

async function mount({ projectRepository, portfolioRepository, ensureHome = true }) {
  let homeState = { messages: [], proposals: [], input: '' };
  const homeConversationRepository = {
    load: async () => homeState,
    save: async (value) => { homeState = value; return value; },
  };
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  await act(async () => { root.render(<App adoptedProjectRepository={projectRepository} sidebarPortfolioRepository={portfolioRepository} homeConversationRepository={homeConversationRepository} profileRepository={completedProfileRepository()} />); });
  await act(async () => Promise.resolve());
  if (ensureHome && !container.querySelector('#home-supervisor-message')) {
    await act(async () => [...container.querySelectorAll('.workspace-shell__nav-item')].find((item) => item.textContent === 'ホーム').click());
  }
  return { container, unmount: () => act(() => { root.unmount(); container.remove(); }) };
}

function selectProject(container) {
  const button = [...container.querySelectorAll('.workspace-shell__nav-item')].find((item) => item.textContent === 'プロジェクト');
  button.click();
}

afterEach(() => {
  document.body.replaceChildren();
  if (typeof globalThis.localStorage?.clear === 'function') globalThis.localStorage.clear();
  if (typeof globalThis.sessionStorage?.clear === 'function') globalThis.sessionStorage.clear();
});

describe('adopted project hydration', () => {
  it.each([
    ['home', 'home:default', 'ホーム'],
    ['project', adoptedCandidate.id, 'プロジェクト'],
  ])('does not render an editable archived %s surface after an F5-equivalent mount', async (surface, id) => {
    const storage = createStorage();
    const portfolioRepository = createSidebarPortfolioRepository({ storage });
    await portfolioRepository.upsert(surface, { id, title: 'アーカイブ済み' });
    await portfolioRepository.archive(surface, id);
    if (surface === 'project') await createAdoptedProjectRepository({ storage }).saveAdopted(adoptedCandidate);
    globalThis.sessionStorage.setItem('kadode:selected-surface', surface);

    const view = await mount({ projectRepository: createAdoptedProjectRepository({ storage }), portfolioRepository, ensureHome: false });
    await act(async () => Promise.resolve());
    expect(view.container.querySelector('#home-supervisor-message')).toBeNull();
    expect(view.container.querySelector('#project-surface-heading')).toBeNull();
    expect(view.container.textContent).toContain('アーカイブ履歴');
    await view.unmount();
  });

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

  it('keeps a newly adopted project when the initial project load resolves later', async () => {
    const pendingLoad = deferred();
    const projectRepository = {
      load: () => pendingLoad.promise,
      saveAdopted: async (candidate) => ({ ...candidate, status: 'adopted' }),
    };
    const view = await mount({ projectRepository });
    const composer = view.container.querySelector('#home-supervisor-message');

    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
      setter.call(composer, '遅延読込より新しい採用プロジェクト');
      composer.dispatchEvent(new Event('input', { bubbles: true }));
      composer.closest('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      await Promise.resolve();
    });
    await act(async () => {
      [...view.container.querySelectorAll('button')].find((button) => button.textContent === 'プロジェクトに採用').click();
      await Promise.resolve();
    });

    expect(view.container.querySelector('[aria-current="page"]').textContent).toBe('プロジェクト');
    expect(view.container.querySelector('#project-surface-heading').textContent).toBe('遅延読込より新しい採用プロジェクト');

    await act(async () => pendingLoad.resolve(null));
    expect(view.container.querySelector('#project-surface-heading').textContent).toBe('遅延読込より新しい採用プロジェクト');
    await view.unmount();
  });
});
