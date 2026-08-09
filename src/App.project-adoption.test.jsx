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

async function mount({ projectRepository, portfolioRepository, ensureHome = true, homeInitial }) {
  let homeState = homeInitial ?? { messages: [], proposals: [], input: '' };
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
  it('mirrors a sent Home conversation into the sidebar immediately and reopens it', async () => {
    const portfolioRepository = createSidebarPortfolioRepository({ storage: createStorage() });
    const view = await mount({ projectRepository: createAdoptedProjectRepository({ storage: createStorage() }), portfolioRepository });
    const composer = view.container.querySelector('#home-supervisor-message');
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
      setter.call(composer, '地域の小さな工場の受注管理を助けたい');
      composer.dispatchEvent(new Event('input', { bubbles: true }));
      composer.closest('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      await Promise.resolve();
    });
    const recent = [...view.container.querySelectorAll('[aria-label="最近の項目"] button')].find((button) => button.textContent === '地域の小さな工場の受注管理を助けたい');
    expect(recent).toBeTruthy();
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
      setter.call(composer, '商店街の空き店舗活用を考えたい');
      composer.dispatchEvent(new Event('input', { bubbles: true }));
      composer.closest('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      await Promise.resolve();
    });
    expect([...view.container.querySelectorAll('[aria-label="最近の項目"] button')].some((button) => button.textContent === '商店街の空き店舗活用を考えたい')).toBe(true);
    await act(async () => { recent.click(); await Promise.resolve(); });
    expect(view.container.querySelector('#home-supervisor-message')).toBeTruthy();
    const reopenedConversation = view.container.querySelector('[aria-label="会話履歴"]');
    expect(reopenedConversation.textContent).toContain('地域の小さな工場の受注管理を助けたい');
    expect(reopenedConversation.textContent).not.toContain('商店街の空き店舗活用を考えたい');
    await view.unmount();
  });

  it('keeps an item and the current surface when archive persistence fails', async () => {
    const portfolio = { home: [{ id: 'home:default', title: '保存済みの会話', archived: false, updatedAt: 1 }], project: [], knowledge: [] };
    const portfolioRepository = { load: async () => portfolio, ensure: async () => portfolio, archive: async () => { throw new Error('offline'); } };
    const view = await mount({ projectRepository: createAdoptedProjectRepository({ storage: createStorage() }), portfolioRepository });
    const archiveButton = view.container.querySelector('[aria-label="保存済みの会話をアーカイブ"]');
    await act(async () => { archiveButton.click(); await Promise.resolve(); });
    expect(view.container.textContent).toContain('保存済みの会話');
    expect(view.container.querySelector('[role="alert"]').textContent).toContain('アーカイブできませんでした');
    expect(view.container.querySelector('#home-supervisor-message')).toBeTruthy();
    await view.unmount();
  });

  it('reports a failed persisted-context mirror without an unhandled rejection', async () => {
    const portfolioRepository = { load: async () => ({ home: [], project: [], knowledge: [] }), ensure: async () => { throw new Error('offline'); }, archive: async () => ({ home: [], project: [], knowledge: [] }) };
    const homeInitial = { messages: [{ role: 'user', content: '保存済み会話' }], proposals: [], input: '' };
    const view = await mount({ projectRepository: createAdoptedProjectRepository({ storage: createStorage() }), portfolioRepository, homeInitial });
    await act(async () => Promise.resolve());
    expect(view.container.querySelector('[role="alert"]').textContent).toContain('履歴を読み込めませんでした');
    await view.unmount();
  });

  it('reopens multiple persisted Project titles from their own real snapshots', async () => {
    const portfolioRepository = createSidebarPortfolioRepository({ storage: createStorage() });
    const firstProject = { ...adoptedCandidate, id: 'project-one', title: '町工場の受注管理' };
    const secondProject = { ...adoptedCandidate, id: 'project-two', title: '商店街の空き店舗活用' };
    await portfolioRepository.upsert('project', { id: firstProject.id, title: firstProject.title, snapshot: firstProject });
    await portfolioRepository.upsert('project', { id: secondProject.id, title: secondProject.title, snapshot: secondProject });
    let currentProject = null;
    const projectRepository = { load: async () => currentProject, saveAdopted: async (value) => { currentProject = value; return value; } };
    const view = await mount({ projectRepository, portfolioRepository });
    const first = [...view.container.querySelectorAll('[aria-label="最近の項目"] button')].find((button) => button.textContent === firstProject.title);
    await act(async () => { first.click(); await Promise.resolve(); });
    expect(view.container.querySelector('#project-surface-heading').textContent).toBe(firstProject.title);
    await view.unmount();
  });

  it('blocks an archived active Home snapshot after F5 and still reopens another conversation', async () => {
    const portfolioRepository = createSidebarPortfolioRepository({ storage: createStorage() });
    const firstSnapshot = { messages: [{ role: 'user', content: '残している会話' }], proposals: [], input: '' };
    const archivedSnapshot = { messages: [{ role: 'user', content: 'アーカイブした会話' }], proposals: [], input: '' };
    await portfolioRepository.upsertAndActivateHome({ id: 'home:first', title: '残している会話', snapshot: firstSnapshot });
    await portfolioRepository.upsertAndActivateHome({ id: 'home:archived', title: 'アーカイブした会話', snapshot: archivedSnapshot });
    await portfolioRepository.archive('home', 'home:archived');
    globalThis.sessionStorage.setItem('kadode:selected-surface', 'home');
    const view = await mount({ projectRepository: createAdoptedProjectRepository({ storage: createStorage() }), portfolioRepository, homeInitial: archivedSnapshot, ensureHome: false });
    await act(async () => Promise.resolve());
    expect(view.container.querySelector('#home-supervisor-message')).toBeNull();
    const first = [...view.container.querySelectorAll('[aria-label="最近の項目"] button')].find((button) => button.textContent === '残している会話');
    await act(async () => { first.click(); await Promise.resolve(); });
    expect(view.container.querySelector('#home-supervisor-message')).toBeTruthy();
    expect(view.container.querySelector('[aria-label="会話履歴"]').textContent).toContain('残している会話');
    expect(view.container.querySelector('[aria-label="会話履歴"]').textContent).not.toContain('アーカイブした会話');
    await view.unmount();
  });

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
