import { expect, it, vi } from 'vitest';
import { createLocalDashboardClient, LocalDashboardClientError } from './localDashboardClient.js';
const location = { origin: 'http://localhost:8765', hostname: 'localhost' };
const response = (body, status = 200) => ({ ok: status === 200, status, json: async () => body });
const status = () => response({ controller: 'running', csrf_token: 'synthetic-csrf', services: {} });

it('keeps lifecycle retries stable and separates restore from archive', async () => {
  const fetchImpl = vi.fn().mockResolvedValueOnce(status()).mockResolvedValueOnce(response({}, 503))
    .mockResolvedValueOnce(status()).mockResolvedValueOnce(response({ id: 'new-tip', revision: 2, replayed: true }))
    .mockResolvedValueOnce(status()).mockResolvedValueOnce(response({ id: 'restored-tip', revision: 3, replayed: false }));
  let keys = 0;
  const client = createLocalDashboardClient({ location, fetchImpl, createIdempotencyKey: () => `intent-${++keys}` });
  await expect(client.archiveRecord('idea', 'id/1', 1)).rejects.toMatchObject({ kind: 'unavailable' });
  await expect(client.archiveRecord('idea', 'id/1', 1)).resolves.toEqual({ id: 'new-tip', revision: 2, replayed: true });
  await client.restoreRecord('idea', 'new-tip', 2);
  const writes = [1, 3, 5].map(index => fetchImpl.mock.calls[index]);
  expect(writes.map(([url]) => url)).toEqual(['/api/records/idea/id%2F1/archive', '/api/records/idea/id%2F1/archive', '/api/records/idea/new-tip/restore']);
  expect(writes.map(([, request]) => JSON.parse(request.body).idempotency_key)).toEqual(['intent-1', 'intent-1', 'intent-2']);
  for (const [, request] of writes) {
    expect(request.headers['X-CSRF-Token']).toBe('synthetic-csrf');
    expect(request).toMatchObject({ method: 'POST', mode: 'same-origin', credentials: 'same-origin', redirect: 'error', referrerPolicy: 'no-referrer' });
  }
});

it('rejects invalid lifecycle targets before generating keys or making requests', async () => {
  const fetchImpl = vi.fn();
  const createIdempotencyKey = vi.fn();
  const client = createLocalDashboardClient({ location, fetchImpl, createIdempotencyKey });
  for (const arguments_ of [['source', 'id', 1], ['asset', '', 1], ['idea', 'id', -1], ['asset', 'id', 0], ['idea', 'id', Number.MAX_SAFE_INTEGER]]) {
    await expect(client.archiveRecord(...arguments_)).rejects.toBeInstanceOf(LocalDashboardClientError);
  }
  expect(fetchImpl).not.toHaveBeenCalled();
  expect(createIdempotencyKey).not.toHaveBeenCalled();
});

it('accepts the existing zero-based Idea initial revision', async () => {
  const fetchImpl = vi.fn().mockResolvedValueOnce(status()).mockResolvedValueOnce(response({ id: 'archived-tip', revision: 1, replayed: false }));
  const client = createLocalDashboardClient({ location, fetchImpl, createIdempotencyKey: () => 'synthetic-intent' });
  await expect(client.archiveRecord('idea', 'initial', 0)).resolves.toMatchObject({ revision: 1 });
  expect(JSON.parse(fetchImpl.mock.calls[1][1].body).expected_revision).toBe(0);
});

it('projects deleted records through an allowlist and rejects duplicates or unknown types', async () => {
  const item = { id: 'archived-tip', kind: 'asset', title: 'Synthetic', description: 'Synthetic record', revision: 2 };
  const fetchImpl = vi.fn().mockResolvedValueOnce(response({ status: 'ready', records: [{ ...item, secret: 'not shared' }] }))
    .mockResolvedValueOnce(response({ status: 'ready', records: [item, item] }))
    .mockResolvedValueOnce(response({ status: 'ready', records: [{ ...item, kind: 'source' }] }));
  const client = createLocalDashboardClient({ location, fetchImpl });
  await expect(client.getDeletedRecords()).resolves.toEqual({ status: 'ready', records: [item] });
  await expect(client.getDeletedRecords()).rejects.toBeInstanceOf(LocalDashboardClientError);
  await expect(client.getDeletedRecords()).rejects.toBeInstanceOf(LocalDashboardClientError);
});
