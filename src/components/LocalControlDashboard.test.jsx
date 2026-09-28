// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { LocalControlDashboard } from './LocalControlDashboard';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let root;
let container;

async function renderDashboard(props) {
  container = document.createElement('div');
  container.style.width = '1280px';
  document.body.append(container);
  root = createRoot(container);
  await act(async () => root.render(<LocalControlDashboard {...props} />));
  return container;
}

afterEach(async () => {
  if (root) await act(async () => root.unmount());
  container?.remove();
  root = undefined;
  container = undefined;
});

describe('LocalControlDashboard', () => {
  it('renders accessible loading state and disables lifecycle actions while loading', async () => {
    let resolve;
    const client = { getSnapshot: () => new Promise((done) => { resolve = done; }) };
    const view = await renderDashboard({ client });

    expect(view.querySelector('[data-dashboard-state="loading"]')?.textContent).toContain('状態を確認中');
    expect(view.querySelector('button[disabled]')?.textContent).toContain('起動');
    await act(async () => resolve({ state: 'stopped', counts: { Idea: 0, Person: 0, Asset: 0, ReportVersion: 0 }, latest: [] }));
  });

  it('shows canonical counts and only allowlisted safe titles at PC width', async () => {
    const onOpenGraph = vi.fn();
    const view = await renderDashboard({
      onOpenGraph,
      client: { getSnapshot: async () => ({
        state: 'running',
        counts: { Idea: 3, Person: 2, Asset: 5, ReportVersion: 4 },
        latest: [
          { id: 'i1', kind: 'Idea', title: '再利用の仮説', body: 'PRIVATE IDEA BODY' },
          { id: 'p1', kind: 'Person', name: '山田さん', email: 'private@example.test', note: 'PRIVATE NOTE' },
          { id: 'a1', kind: 'Asset', name: '試作資料', content: 'PRIVATE FILE CONTENT' },
          { id: 'r1', kind: 'ReportVersion', title: 'PRIVATE REPORT TITLE', body: 'PRIVATE REPORT BODY' },
          { id: 'x1', kind: 'Person', title: 'unsafe person title', privateMemo: 'PRIVATE MEMO' },
        ],
      }) },
    });

    expect(view.querySelector('[data-dashboard-state="running"]')?.textContent).toContain('稼働中');
    expect([...view.querySelectorAll('dd')].map((item) => item.textContent)).toEqual(['3', '2', '5', '4']);
    expect(view.textContent).toContain('再利用の仮説');
    expect(view.textContent).toContain('山田さん');
    expect(view.textContent).toContain('試作資料');
    expect(view.textContent).toContain('調査レポート');
    for (const privateValue of ['PRIVATE IDEA BODY', 'private@example.test', 'PRIVATE NOTE', 'PRIVATE FILE CONTENT', 'PRIVATE REPORT TITLE', 'PRIVATE REPORT BODY', 'unsafe person title', 'PRIVATE MEMO']) {
      expect(view.textContent).not.toContain(privateValue);
    }
    expect(view.querySelector('[aria-labelledby="counts-heading"] dl')?.className).toContain('grid-cols-2');
    expect(view.querySelector('main')?.getAttribute('aria-labelledby')).toBe('local-control-heading');
    await act(async () => view.querySelector('button')?.click());
    expect(onOpenGraph).not.toHaveBeenCalled();
    await act(async () => [...view.querySelectorAll('button')].find((button) => button.textContent === 'Graphを開く').click());
    expect(onOpenGraph).toHaveBeenCalledOnce();
  });

  it('requires an explicit confirmation before stopping and reports the completed action', async () => {
    let currentState = 'running';
    const client = { getSnapshot: vi.fn(async () => ({ state: currentState, counts: { Idea: 0, Person: 0, Asset: 0, ReportVersion: 0 }, latest: [] })), stop: vi.fn(async () => { currentState = 'stopped'; }) };
    const view = await renderDashboard({ client });

    await act(async () => [...view.querySelectorAll('button')].find((button) => button.textContent === 'Dots.を停止').click());
    expect(client.stop).not.toHaveBeenCalled();
    expect(view.querySelector('[role="alertdialog"]')?.textContent).toContain('操作盤と保存データは残ります');
    await act(async () => [...view.querySelectorAll('button')].find((button) => button.textContent === '停止する').click());

    expect(client.stop).toHaveBeenCalledOnce();
    expect(view.querySelector('[role="status"]')?.textContent).toContain('Dots.を停止しました');
    expect(view.querySelector('[data-dashboard-state="stopped"]')?.textContent).toContain('停止中');
  });

  it('starts only after confirmation from the stopped state', async () => {
    let currentState = 'stopped';
    const client = { getSnapshot: async () => ({ state: currentState, counts: { Idea: 0, Person: 0, Asset: 0, ReportVersion: 0 }, latest: [] }), start: vi.fn(async () => { currentState = 'running'; }) };
    const view = await renderDashboard({ client });
    expect(view.textContent).toContain('保存先と接続が稼働すると、件数と最近の記録を表示できます');
    expect(view.querySelector('[aria-labelledby="counts-heading"]')).toBeNull();
    await act(async () => [...view.querySelectorAll('button')].find((button) => button.textContent === 'Dots.を起動').click());

    expect(view.querySelector('[role="alertdialog"]')?.textContent).toContain('保存データは削除されません');
    expect(client.start).not.toHaveBeenCalled();
    await act(async () => [...view.querySelectorAll('button')].find((button) => button.textContent === '起動する').click());
    expect(client.start).toHaveBeenCalledOnce();
    expect(view.querySelector('[data-dashboard-state="running"]')?.textContent).toContain('稼働中');
  });

  it('moves keyboard focus into confirmation and restores it after Escape', async () => {
    const view = await renderDashboard({ client: { getSnapshot: async () => ({ state: 'running', counts: { Idea: 0, Person: 0, Asset: 0, ReportVersion: 0 }, latest: [] }) } });
    const trigger = [...view.querySelectorAll('button')].find((button) => button.textContent === 'Dots.を停止');
    await act(async () => trigger.click());
    expect(document.activeElement.textContent).toBe('停止する');

    await act(async () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })));
    expect(view.querySelector('[role="alertdialog"]')).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it('distinguishes a read failure from an empty dataset', async () => {
    const view = await renderDashboard({ client: { getSnapshot: async () => { throw new Error('private transport detail'); } } });
    expect(view.querySelector('[data-dashboard-state="error"]')?.textContent).toContain('状態を確認できません');
    expect(view.querySelector('[data-dashboard-state="error"]')?.getAttribute('role')).toBe('alert');
    expect(view.textContent).not.toContain('private transport detail');
    expect(view.querySelector('[aria-labelledby="latest-heading"]')).toBeNull();
  });

  it('shows each service state and hides counts while partially unavailable', async () => {
    const view = await renderDashboard({ client: { getSnapshot: async () => ({
      state: 'degraded',
      services: { database: 'running', api: 'unavailable', tunnel: 'stopped' },
      counts: { Idea: 2, Person: 1, Asset: 0, ReportVersion: 0 },
      latest: [],
    }) } });
    expect(view.querySelector('[data-dashboard-state="degraded"]')?.textContent).toContain('一部利用できません');
    expect(view.querySelector('[aria-label="サービスごとの状態"]')?.textContent).toContain('ChatGPT接続停止中');
    expect(view.querySelector('[data-service="database"] .local-control__lamp--running')).not.toBeNull();
    expect(view.querySelector('[data-service="tunnel"] .local-control__lamp--stopped')).not.toBeNull();
    expect(view.querySelector('[data-service="api"] .local-control__lamp')).toBeNull();
    expect(view.querySelector('[aria-labelledby="counts-heading"]')).toBeNull();
  });

  it('shows the deleted-record restore list only in service-only mode', async () => {
    const client = {
      getServiceSnapshot: vi.fn(async () => ({ state: 'running', counts: { Idea: 0, Person: 0, Asset: 0, ReportVersion: 0 }, latest: [] })),
      getDeletedRecords: vi.fn(async () => ({ status: 'ready', records: [
        { id: 'asset-1', kind: 'asset', title: '復元できる資料', description: '概要', revision: 2 },
      ] })),
    };
    const view = await renderDashboard({ client, serviceOnly: true });
    expect(view.querySelector('[aria-labelledby="deleted-records-heading"]')).not.toBeNull();
    expect(view.textContent).toContain('復元できる資料');
    expect(client.getDeletedRecords).toHaveBeenCalledWith({ signal: expect.any(AbortSignal) });
  });
});
