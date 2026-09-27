// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import { LocalDeletedRecords } from './LocalDeletedRecords';
import { createLocalDashboardClient } from '../runtime/localDashboardClient.js';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let mounted;

async function renderDeletedRecords(client) {
  const container = document.createElement('div');
  container.style.width = '1280px';
  document.body.append(container);
  const root = createRoot(container);
  mounted = { root, container };
  await act(async () => root.render(<LocalDeletedRecords client={client} />));
  return container;
}

afterEach(async () => {
  if (mounted) await act(async () => { mounted.root.unmount(); mounted.container.remove(); });
  mounted = null;
});

it('shows an explicit loading state and aborts its read when unmounted', async () => {
  let signal;
  const client = { getDeletedRecords: vi.fn((options) => {
    signal = options.signal;
    return new Promise(() => {});
  }) };
  const view = await renderDeletedRecords(client);
  expect(view.querySelector('[role="status"]')?.textContent).toContain('読み込んでいます');
  await act(async () => mounted.root.unmount());
  mounted.container.remove();
  expect(signal.aborted).toBe(true);
  mounted = null;
});

it('shows deleted ideas and assets then removes a restored record from the refreshed list', async () => {
  const records = [
    { id: 'idea-1', kind: 'idea', title: '協業案', description: '内容A', revision: 0 },
    { id: 'asset-1', kind: 'asset', title: '経験', description: '内容B', revision: 3 },
  ];
  const client = {
    getDeletedRecords: vi.fn().mockResolvedValueOnce({ status: 'ready', records })
      .mockResolvedValueOnce({ status: 'ready', records: [records[1]] }),
    restoreRecord: vi.fn().mockResolvedValue({ id: 'idea-1', revision: 1, replayed: false }),
  };
  const view = await renderDeletedRecords(client);
  expect(view.querySelectorAll('.local-deleted-records__item')).toHaveLength(2);
  expect(view.textContent).toContain('アイデア');
  expect(view.textContent).toContain('アセット');
  expect(view.textContent).toContain('協業案');
  expect(view.textContent).toContain('内容A');

  await act(async () => [...view.querySelectorAll('button')].find((button) => button.textContent === '復元').click());
  expect(client.restoreRecord).toHaveBeenCalledWith('idea', 'idea-1', 0, { signal: expect.any(AbortSignal) });
  expect(client.getDeletedRecords).toHaveBeenCalledTimes(2);
  expect(view.querySelectorAll('.local-deleted-records__item')).toHaveLength(1);
  expect(view.textContent).toContain('協業案を復元しました');
  expect(view.textContent).not.toContain('内容A');
});

it('disables every restore action while an operation is pending and keeps the record after conflicts', async () => {
  let rejectRestore;
  const record = { id: 'asset-1', kind: 'asset', title: '資料', description: '説明', revision: 2 };
  const client = {
    getDeletedRecords: vi.fn(async () => ({ status: 'ready', records: [record] })),
    restoreRecord: vi.fn(() => new Promise((resolve, reject) => { rejectRestore = reject; })),
  };
  const view = await renderDeletedRecords(client);
  const restoreButton = [...view.querySelectorAll('button')].find((button) => button.textContent === '復元');
  await act(async () => restoreButton.click());
  expect(restoreButton.disabled).toBe(true);
  expect(restoreButton.textContent).toBe('復元中…');
  await act(async () => rejectRestore({ kind: 'conflict' }));
  expect(view.querySelectorAll('.local-deleted-records__item')).toHaveLength(1);
  expect(view.querySelector('[role="status"]')?.textContent).toContain('他の更新');
});

it('aborts a pending restore when the deleted-record list unmounts', async () => {
  let restoreSignal;
  const record = { id: 'asset-1', kind: 'asset', title: '離脱する資料', description: '', revision: 2 };
  const client = {
    getDeletedRecords: vi.fn(async () => ({ status: 'ready', records: [record] })),
    restoreRecord: vi.fn((_kind, _id, _revision, { signal }) => {
      restoreSignal = signal;
      return new Promise(() => {});
    }),
  };
  const view = await renderDeletedRecords(client);
  await act(async () => [...view.querySelectorAll('button')].find((button) => button.textContent === '復元').click());
  expect(restoreSignal.aborted).toBe(false);

  await act(async () => mounted.root.unmount());
  expect(restoreSignal.aborted).toBe(true);
  mounted.container.remove();
  mounted = null;
});

it('retries an unavailable restore with the same intent key and recovers the list', async () => {
  const record = { id: 'asset-1', kind: 'asset', title: '再試行する資料', description: '概要', revision: 2 };
  const response = (body, status = 200) => ({ ok: status === 200, status, json: async () => body });
  const restoreRequests = [];
  const fetchImpl = vi.fn(async (path, options = {}) => {
    if (path === '/api/deleted-records') {
      return response(restoreRequests.length < 2
        ? { status: 'ready', records: [record] }
        : { status: 'empty', records: [] });
    }
    if (path === '/api/status') {
      return response({ controller: 'running', csrf_token: 'synthetic-csrf', services: {} });
    }
    if (path === '/api/records/asset/asset-1/restore') {
      restoreRequests.push(JSON.parse(options.body));
      return restoreRequests.length === 1
        ? response({}, 503)
        : response({ id: 'asset-restored', revision: 3, replayed: true });
    }
    throw new Error(`Unexpected request: ${path}`);
  });
  const createIdempotencyKey = vi.fn(() => 'restore-intent-1');
  const client = createLocalDashboardClient({
    fetchImpl,
    location: { origin: 'http://localhost:8765', hostname: 'localhost' },
    createIdempotencyKey,
  });
  const view = await renderDeletedRecords(client);

  const restoreButton = () => [...view.querySelectorAll('button')].find((button) => button.textContent === '復元');
  await act(async () => restoreButton().click());
  expect(view.querySelectorAll('.local-deleted-records__item')).toHaveLength(1);
  expect(view.textContent).toContain('復元できませんでした');

  await act(async () => restoreButton().click());
  expect(restoreRequests).toEqual([
    { expected_revision: 2, idempotency_key: 'restore-intent-1' },
    { expected_revision: 2, idempotency_key: 'restore-intent-1' },
  ]);
  expect(createIdempotencyKey).toHaveBeenCalledOnce();
  expect(view.querySelectorAll('.local-deleted-records__item')).toHaveLength(0);
  expect(view.textContent).toContain('再試行する資料を復元しました');
});

it('keeps a restored record visible when the follow-up list read fails and recovers on reload', async () => {
  const record = { id: 'idea-1', kind: 'idea', title: '更新が失敗する案', description: '', revision: 0 };
  const client = {
    getDeletedRecords: vi.fn().mockResolvedValueOnce({ status: 'ready', records: [record] })
      .mockRejectedValueOnce(new Error('temporary read failure'))
      .mockResolvedValueOnce({ status: 'empty', records: [] }),
    restoreRecord: vi.fn().mockResolvedValue({ id: 'idea-restored', revision: 1, replayed: false }),
  };
  const view = await renderDeletedRecords(client);

  await act(async () => [...view.querySelectorAll('button')].find((button) => button.textContent === '復元').click());
  expect(view.querySelectorAll('.local-deleted-records__item')).toHaveLength(1);
  expect(view.textContent).toContain('削除済み一覧を更新できませんでした');
  expect(view.querySelector('[role="alert"]')).not.toBeNull();

  await act(async () => [...view.querySelectorAll('button')].find((button) => button.textContent === '再読み込み').click());
  expect(client.getDeletedRecords).toHaveBeenCalledTimes(3);
  expect(view.querySelectorAll('.local-deleted-records__item')).toHaveLength(0);
  expect(view.textContent).toContain('削除済みの記録はありません');
});

it('clears an aborted restore when the client changes', async () => {
  let rejectRestore;
  let restoreSignal;
  const record = { id: 'asset-1', kind: 'asset', title: '再読込する資料', description: '', revision: 2 };
  const firstClient = {
    getDeletedRecords: vi.fn(async () => ({ status: 'ready', records: [record] })),
    restoreRecord: vi.fn((kind, id, revision, { signal }) => {
      restoreSignal = signal;
      return new Promise((resolve, reject) => { rejectRestore = reject; });
    }),
  };
  const nextClient = { getDeletedRecords: vi.fn(async () => ({ status: 'ready', records: [record] })) };
  const view = await renderDeletedRecords(firstClient);
  await act(async () => [...view.querySelectorAll('button')].find((button) => button.textContent === '復元').click());
  expect([...view.querySelectorAll('button')].find((button) => button.textContent === '復元中…').disabled).toBe(true);

  await act(async () => mounted.root.render(<LocalDeletedRecords client={nextClient} />));
  expect(restoreSignal.aborted).toBe(true);
  const retryButton = [...view.querySelectorAll('button')].find((button) => button.textContent === '復元');
  expect(retryButton.disabled).toBe(false);
  expect(view.textContent).not.toContain('復元中');
  await act(async () => rejectRestore({ kind: 'unavailable' }));
  expect(view.textContent).not.toContain('復元できませんでした');
});

it('distinguishes stopped, empty, and failed reads and lets the user retry', async () => {
  for (const result of [
    { status: 'stopped', records: [] },
    { status: 'empty', records: [] },
  ]) {
    const client = { getDeletedRecords: vi.fn(async () => result) };
    const view = await renderDeletedRecords(client);
    expect(view.textContent).toContain(result.status === 'stopped' ? 'Dots.が停止中' : '削除済みの記録はありません');
    await act(async () => { mounted.root.unmount(); mounted.container.remove(); });
    mounted = null;
  }

  const client = { getDeletedRecords: vi.fn().mockRejectedValueOnce(new Error('private transport detail'))
    .mockResolvedValueOnce({ status: 'empty', records: [] }) };
  const view = await renderDeletedRecords(client);
  expect(view.querySelector('[role="alert"]')?.textContent).toContain('読み込めませんでした');
  expect(view.textContent).not.toContain('private transport detail');
  await act(async () => [...view.querySelectorAll('button')].find((button) => button.textContent === '再読み込み').click());
  expect(client.getDeletedRecords).toHaveBeenCalledTimes(2);
  expect(view.textContent).toContain('削除済みの記録はありません');
});
