import { describe, expect, it, vi } from 'vitest';
import { createLocalDashboardClient, LocalDashboardClientError } from './localDashboardClient';

const localLocation = { origin: 'http://localhost:4173', hostname: 'localhost' };
const servicesRunning = { database: 'running', api: 'running', tunnel: 'running' };

function jsonResponse(body, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

it('passes bounded public citations and distinguishes missing sources through the real home client', async () => {
  const citations = Array.from({ length: 8 }, () => []);
  citations[0] = [
    { url: 'https://example.test/report?id=1#section', title: '公開資料', private_body: 'SECRET' },
    { url: 'https://example.test/report?refresh_token=secret', title: 'token URL' },
    { url: 'https://example.test/share?rlkey=secret', title: 'share key URL' },
  ];
  const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({
    status: 'ready', assets: [], profile: null,
    ideas: [{ id: 'idea-cited', title: '案', summary: '', description: '',
      research_status: 'research_sources_missing', brief_sections: Array(8).fill('概要'),
      brief_revision: 1, brief_citations: citations }],
  }));
  const home = await createLocalDashboardClient({ fetchImpl, location: localLocation }).getHome();
  expect(home.ideas[0].research_status).toBe('research_sources_missing');
  expect(home.ideas[0].brief_citations[0]).toEqual([{ url: 'https://example.test/report?id=1#section', title: '公開資料' }]);
  expect(JSON.stringify(home)).not.toContain('SECRET');
});

it('maps common asset revisions and sharing policy without exposing other server fields', async () => {
  const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({
    status: 'ready', ideas: [], profile: { display_name: 'private' },
    assets: [{ id: 'asset-1', name: '経験', kind: 'experience', description: '内容', revision: 3, egress_policy: 'shareable', details: 'PRIVATE' }],
  }));
  const home = await createLocalDashboardClient({ fetchImpl, location: localLocation }).getHome();
  expect(home.assets).toEqual([{ id: 'asset-1', name: '経験', description: '内容', revision: 3, egress_policy: 'shareable' }]);
  expect(JSON.stringify(home)).not.toContain('PRIVATE');
});

it('fails closed when an asset lacks a current revision or has an unknown sharing policy', async () => {
  for (const asset of [
    { id: 'asset-1', name: '題名', description: '内容', revision: 0, egress_policy: 'local_only' },
    { id: 'asset-1', name: '題名', description: '内容', revision: 1, egress_policy: 'public' },
  ]) {
    const client = createLocalDashboardClient({
      location: localLocation,
      fetchImpl: vi.fn().mockResolvedValueOnce(jsonResponse({ status: 'ready', ideas: [], assets: [asset] })),
    });
    await expect(client.getHome()).rejects.toBeInstanceOf(LocalDashboardClientError);
  }
});

it('updates one asset with CSRF, expected revision and stable idempotency key, rotating on changed payload', async () => {
  let generated = 0;
  const fetchImpl = vi.fn()
    .mockResolvedValueOnce(statusResponse())
    .mockResolvedValueOnce(jsonResponse({ id: 'asset-2', revision: 4 }))
    .mockResolvedValueOnce(statusResponse())
    .mockResolvedValueOnce(jsonResponse({ id: 'asset-2', revision: 4, replayed: true }))
    .mockResolvedValueOnce(statusResponse())
    .mockResolvedValueOnce(jsonResponse({ id: 'asset-3', revision: 4 }));
  const client = createLocalDashboardClient({ fetchImpl, location: localLocation, createIdempotencyKey: () => `asset-edit-${++generated}` });

  const first = { name: '更新題名', description: '更新内容', expectedRevision: 3 };
  await expect(client.saveAsset('asset/1', first)).resolves.toEqual({ id: 'asset-2', revision: 4 });
  await expect(client.saveAsset('asset/1', first)).resolves.toEqual({ id: 'asset-2', revision: 4 });
  await expect(client.saveAsset('asset/1', { ...first, name: '別の題名' })).resolves.toEqual({ id: 'asset-3', revision: 4 });

  expect(fetchImpl.mock.calls.map(([path]) => path)).toEqual([
    '/api/status', '/api/assets/asset%2F1', '/api/status', '/api/assets/asset%2F1', '/api/status', '/api/assets/asset%2F1',
  ]);
  const requests = [fetchImpl.mock.calls[1][1], fetchImpl.mock.calls[3][1], fetchImpl.mock.calls[5][1]];
  expect(requests.map((request) => request.method)).toEqual(['PUT', 'PUT', 'PUT']);
  expect(requests[0].headers['X-CSRF-Token']).toBe('csrf-from-status');
  expect(JSON.parse(requests[0].body)).toEqual({ name: '更新題名', description: '更新内容', expected_revision: 3, idempotency_key: 'asset-edit-1' });
  expect(JSON.parse(requests[1].body).idempotency_key).toBe('asset-edit-1');
  expect(JSON.parse(requests[2].body).idempotency_key).toBe('asset-edit-2');
  for (const request of requests) expect(JSON.parse(request.body)).not.toHaveProperty('egress_policy');
});

it('keeps the same asset idempotency key when a save transport fails and is retried', async () => {
  let generated = 0;
  const fetchImpl = vi.fn()
    .mockResolvedValueOnce(statusResponse())
    .mockRejectedValueOnce(new Error('offline'))
    .mockResolvedValueOnce(statusResponse())
    .mockResolvedValueOnce(jsonResponse({ id: 'asset-next', revision: 2 }));
  const client = createLocalDashboardClient({ fetchImpl, location: localLocation, createIdempotencyKey: () => `retry-${++generated}` });
  const edit = { name: '題名', description: '内容', expectedRevision: 1 };

  await expect(client.saveAsset('asset-1', edit)).rejects.toMatchObject({ kind: 'unavailable' });
  await expect(client.saveAsset('asset-1', edit)).resolves.toEqual({ id: 'asset-next', revision: 2 });
  expect(JSON.parse(fetchImpl.mock.calls[1][1].body).idempotency_key).toBe('retry-1');
  expect(JSON.parse(fetchImpl.mock.calls[3][1].body).idempotency_key).toBe('retry-1');
});

it('rejects asset edits outside the server title, content and revision bounds before requesting', async () => {
  const fetchImpl = vi.fn();
  const client = createLocalDashboardClient({ fetchImpl, location: localLocation });
  for (const edit of [
    { name: '', description: '', expectedRevision: 1 },
    { name: 'x'.repeat(201), description: '', expectedRevision: 1 },
    { name: '題名', description: 'x'.repeat(4001), expectedRevision: 1 },
    { name: '題名', description: '', expectedRevision: 0 },
  ]) {
    await expect(client.saveAsset('asset-1', edit)).rejects.toBeInstanceOf(LocalDashboardClientError);
  }
  expect(fetchImpl).not.toHaveBeenCalled();
});

function statusResponse(overrides = {}) {
  return jsonResponse({ controller: 'running', csrf_token: 'csrf-from-status', services: servicesRunning, ...overrides });
}

function overviewResponse(overrides = {}) {
  return jsonResponse({
    status: 'ready',
    count_basis: 'stored_active_records',
    counts: { idea_records: 2, person_records: 1, asset_records: 3, report_version_records: 4 },
    recent: [
      { id: 'idea-1', kind: 'idea', title: '着想', updated_at: '2026-09-25T10:00:00Z' },
      { id: 'person-1', kind: 'person', title: '山田さん', updated_at: '2026-09-25T09:00:00Z', contact: 'private@example.test' },
      { id: 'asset-1', kind: 'asset', title: '試作資料', updated_at: '2026-09-25T08:00:00Z', details: 'private' },
      { id: 'report-1', kind: 'report_version', title: 'PRIVATE REPORT TITLE', updated_at: '2026-09-25T07:00:00Z' },
      { id: 'unsafe-1', kind: 'person', name: 'unsafe alternate field', private_note: 'private' },
      { id: 'unknown-1', kind: 'decision', title: 'Unknown type' },
    ],
    ...overrides,
  });
}

describe('Local dashboard client', () => {
  it('does not promote missing or unrecognized research states from a saved brief', async () => {
    for (const research_status of [undefined, 'complete', { status: 'completed' }]) {
      const fetchImpl = vi.fn().mockResolvedValueOnce(jsonResponse({
        status: 'ready', assets: [], profile: null,
        ideas: [{ id: 'draft', title: '未確認案', summary: '', description: '', research_status, brief_sections: Array(8).fill('概要'), brief_revision: 1 }],
      }));
      const home = await createLocalDashboardClient({ fetchImpl, location: localLocation }).getHome();
      expect(home.ideas[0].research_status).toBe('unknown');
    }
  });
  it('preserves the server-validated researched state with a complete brief', async () => {
    const fetchImpl = vi.fn().mockResolvedValueOnce(jsonResponse({
      status: 'ready', assets: [], profile: null,
      ideas: [{ id: 'idea-1', title: '調査案', summary: '', description: '', research_status: 'researched', brief_sections: Array(8).fill('確認済み概要'), brief_revision: 1 }],
    }));
    const home = await createLocalDashboardClient({ fetchImpl, location: localLocation }).getHome();
    expect(home.ideas[0].research_status).toBe('researched');
  });
  it('does not display researched for an absent or partial brief', async () => {
    for (const brief of [{}, { brief_sections: ['概要', ...Array(7).fill('')], brief_revision: 1 }]) {
      const fetchImpl = vi.fn().mockResolvedValueOnce(jsonResponse({
        status: 'ready', assets: [], profile: null,
        ideas: [{ id: 'idea-1', title: '不完全な案', summary: '', description: '', research_status: 'researched', ...brief }],
      }));
      const home = await createLocalDashboardClient({ fetchImpl, location: localLocation }).getHome();
      expect(home.ideas[0].research_status).toBe('unknown');
    }
  });
  it('preserves only the eight public idea brief sections for the home view', async () => {
    const sections = ['要約', '', '', '', '', '実現可能性を訂正', '', ''];
    const fetchImpl = vi.fn().mockResolvedValueOnce(jsonResponse({
      status: 'ready',
      ideas: [{ id: 'idea-1', title: '試験案', summary: '旧要約', description: '', research_status: 'unresearched', brief_sections: sections, brief_revision: 2, private_note: 'SECRET' }],
      assets: [], profile: null,
    }));
    const home = await createLocalDashboardClient({ fetchImpl, location: localLocation }).getHome();
    expect(home.ideas[0]).toEqual({ id: 'idea-1', title: '試験案', summary: '旧要約', description: '', research_status: 'unresearched', brief_sections: sections, brief_revision: 2 });
    expect(JSON.stringify(home)).not.toContain('SECRET');
  });

  it('reads a bounded graph projection and submits a common asset edit with CSRF', async () => {
    const fetchImpl = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ status: 'ready', nodes: [{ id: 'idea-1', kind: 'idea', label: '事業案', private_note: 'PRIVATE' }], edges: [], truncated: false }))
      .mockResolvedValueOnce(statusResponse())
      .mockResolvedValueOnce(jsonResponse({ id: 'asset-new', revision: 2 }));
    const client = createLocalDashboardClient({ fetchImpl, location: localLocation, createIdempotencyKey: () => 'edit-one' });
    expect(await client.getGraph()).toEqual({ status: 'ready', nodes: [{ id: 'idea-1', kind: 'idea', label: '事業案' }], edges: [], semantic_edges: [], truncated: false });
    expect(await client.saveAsset('asset-old', { name: '題名', description: '内容', expectedRevision: 1 })).toEqual({ id: 'asset-new', revision: 2 });
    expect(fetchImpl.mock.calls.map(([path]) => path)).toEqual(['/api/graph', '/api/status', '/api/assets/asset-old']);
    expect(fetchImpl.mock.calls[2][1]).toEqual(expect.objectContaining({
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': 'csrf-from-status' },
      body: JSON.stringify({ name: '題名', description: '内容', expected_revision: 1, idempotency_key: 'edit-one' }),
    }));
  });
  it('validates and allowlists semantic Facet region results', async () => {
    const payload = {
      status: 'ready', facet_id: 'facet/root', depth: 1,
      hits: [{
        id: 'idea-1', kind: 'idea', title: '事業案', root_facet_id: 'facet/root', matched_facet_id: 'facet/child',
        depth: 1, classification_status: 'inferred', classification_evidence_ids: ['ev-class'],
        taxonomy_status_path: ['confirmed'], taxonomy_evidence_path: [['ev-tax']], evidence_ids: ['ev-tax', 'ev-class'],
        facet_path: [
          { facet_id: 'facet/root', label: '事業領域', depth: 0 },
          { facet_id: 'facet/child', label: '創業案', depth: 1 },
        ],
        private_note: 'PRIVATE',
      }, {
        id: 'idea-1', kind: 'idea', title: '事業案', root_facet_id: 'facet/root', matched_facet_id: 'facet/root',
        depth: 0, classification_status: 'confirmed', classification_evidence_ids: ['ev-direct'],
        taxonomy_status_path: [], taxonomy_evidence_path: [], evidence_ids: ['ev-direct'],
        facet_path: [{ facet_id: 'facet/root', label: `${'n'.repeat(120)}: ${'v'.repeat(240)}`, depth: 0 }],
      }],
    };
    const fetchImpl = vi.fn().mockResolvedValueOnce(jsonResponse(payload));
    const client = createLocalDashboardClient({ fetchImpl, location: localLocation });
    const result = await client.getFacetRegion('facet/root', 1);
    expect(result.hits[0]).toMatchObject({ classification_status: 'inferred', evidence_ids: ['ev-tax', 'ev-class'], facet_path: [
      { facet_id: 'facet/root', label: '事業領域', depth: 0 },
      { facet_id: 'facet/child', label: '創業案', depth: 1 },
    ] });
    expect(result.hits).toHaveLength(2);
    expect(result.hits[1].matched_facet_id).toBe('facet/root');
    const duplicateMembership = createLocalDashboardClient({
      location: localLocation,
      fetchImpl: vi.fn().mockResolvedValueOnce(jsonResponse({
        ...payload, hits: [payload.hits[0], { ...payload.hits[0] }],
      })),
    });
    await expect(duplicateMembership.getFacetRegion('facet/root', 1)).rejects.toBeInstanceOf(LocalDashboardClientError);
    expect(JSON.stringify(result)).not.toContain('PRIVATE');
    expect(fetchImpl.mock.calls[0][0]).toBe('/api/graph/facet-region?facet_id=facet%2Froot&depth=1');
    const malformed = createLocalDashboardClient({
      location: localLocation,
      fetchImpl: vi.fn().mockResolvedValueOnce(jsonResponse({ ...payload, hits: [{ ...payload.hits[0], evidence_ids: [] }] })),
    });
    await expect(malformed.getFacetRegion('facet/root', 1)).rejects.toBeInstanceOf(LocalDashboardClientError);
    const brokenPath = createLocalDashboardClient({
      location: localLocation,
      fetchImpl: vi.fn().mockResolvedValueOnce(jsonResponse({ ...payload, hits: [{ ...payload.hits[0], facet_path: [payload.hits[0].facet_path[1]] }] })),
    });
    await expect(brokenPath.getFacetRegion('facet/root', 1)).rejects.toBeInstanceOf(LocalDashboardClientError);
  });

  it('loads exact semantic edge provenance through the same-origin read route and allowlists safe fields', async () => {
    const payload = {
      status: 'ready', assertion_id: 'assertion/a',
      section: { brief_id: 'brief-1', revision: 2, idea_id: 'idea-1', section_index: 5, title: '市場はある？', content: '合成された概要の根拠章。', raw_payload: 'PRIVATE' },
      evidence: [{ id: 'evidence-1', polarity: 'supports', confidence: 0.82, status: 'active', excerpt: 'PRIVATE', locator: 'PRIVATE' }],
      private_note: 'PRIVATE',
    };
    const fetchImpl = vi.fn().mockResolvedValueOnce(jsonResponse(payload));
    const client = createLocalDashboardClient({ fetchImpl, location: localLocation });
    const controller = new AbortController();
    const result = await client.getSemanticEdgeProvenance('assertion/a', { signal: controller.signal });
    expect(fetchImpl).toHaveBeenCalledWith('/api/graph/semantic-edges/assertion%2Fa/provenance', expect.objectContaining({
      method: 'GET', credentials: 'same-origin', mode: 'same-origin', redirect: 'error', signal: controller.signal,
    }));
    expect(result).toEqual({
      status: 'ready', assertion_id: 'assertion/a',
      section: { brief_id: 'brief-1', revision: 2, idea_id: 'idea-1', section_index: 5, title: '市場はある？', content: '合成された概要の根拠章。' },
      evidence: [{ id: 'evidence-1', polarity: 'supports', confidence: 0.82, status: 'active' }],
    });
    expect(JSON.stringify(result)).not.toContain('PRIVATE');
  });

  it('allows evidence-only provenance for legacy assertions and preserves the stopped state', async () => {
    const legacyClient = createLocalDashboardClient({
      location: localLocation,
      fetchImpl: vi.fn().mockResolvedValueOnce(jsonResponse({ status: 'ready', assertion_id: 'legacy-1', section: null, evidence: [] })),
    });
    expect(await legacyClient.getSemanticEdgeProvenance('legacy-1')).toEqual({
      status: 'ready', assertion_id: 'legacy-1', section: null, evidence: [],
    });
    const stoppedClient = createLocalDashboardClient({
      location: localLocation,
      fetchImpl: vi.fn().mockResolvedValueOnce(jsonResponse({ status: 'stopped', assertion_id: 'legacy-1', section: null, evidence: [] })),
    });
    expect(await stoppedClient.getSemanticEdgeProvenance('legacy-1')).toMatchObject({ status: 'stopped' });
  });

  it('rejects malformed or cross-assertion provenance and aborts on request cancellation', async () => {
    for (const change of [
      { assertion_id: 'other-edge' },
      { section: { brief_id: 'b', revision: 0, idea_id: 'i', section_index: 8, title: '', content: '' } },
      { evidence: [{ id: 'e', polarity: 'supports', confidence: 2, status: 'active' }] },
    ]) {
      const invalidClient = createLocalDashboardClient({
        location: localLocation,
        fetchImpl: vi.fn().mockResolvedValueOnce(jsonResponse({ status: 'ready', assertion_id: 'edge-1', section: null, evidence: [], ...change })),
      });
      await expect(invalidClient.getSemanticEdgeProvenance('edge-1')).rejects.toBeInstanceOf(LocalDashboardClientError);
    }
    const fetchImpl = vi.fn((_path, { signal }) => new Promise((_, reject) => {
      signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true });
    }));
    const client = createLocalDashboardClient({ fetchImpl, location: localLocation });
    const controller = new AbortController();
    const pending = client.getSemanticEdgeProvenance('edge-1', { signal: controller.signal });
    controller.abort();
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
  });
  it('reads same-origin status and overview, mapping only safe UI fields and stored-record counts', async () => {
    const fetchImpl = vi.fn()
      .mockResolvedValueOnce(statusResponse())
      .mockResolvedValueOnce(overviewResponse());
    const client = createLocalDashboardClient({ fetchImpl, location: localLocation });
    const controller = new AbortController();

    const snapshot = await client.getSnapshot({ signal: controller.signal });

    expect(snapshot).toEqual({
      state: 'running',
      services: servicesRunning,
      counts: { Idea: 2, Person: 1, Asset: 3, ReportVersion: 4 },
      latest: [
        { id: 'idea-1', kind: 'Idea', title: '着想' },
        { id: 'person-1', kind: 'Person', name: '山田さん' },
        { id: 'asset-1', kind: 'Asset', name: '試作資料' },
        { id: 'report-1', kind: 'ReportVersion', title: '調査レポート' },
      ],
      countBasis: 'stored_active_records',
    });
    expect(fetchImpl).toHaveBeenNthCalledWith(1, '/api/status', expect.objectContaining({
      method: 'GET', credentials: 'same-origin', mode: 'same-origin', redirect: 'error', signal: controller.signal,
    }));
    expect(fetchImpl).toHaveBeenNthCalledWith(2, '/api/overview', expect.objectContaining({
      method: 'GET', credentials: 'same-origin', mode: 'same-origin', redirect: 'error', signal: controller.signal,
    }));
    for (const [, options] of fetchImpl.mock.calls) {
      expect(options.headers).not.toHaveProperty('Authorization');
      expect(options).not.toHaveProperty('baseURL');
    }
    const serialized = JSON.stringify(snapshot);
    expect(serialized).not.toContain('private@example.test');
    expect(serialized).not.toContain('private_note');
    expect(serialized).not.toContain('PRIVATE REPORT TITLE');
    expect(serialized).not.toContain('unsafe alternate field');
  });

  it('maps empty overview to running and distinguishes stopped and degraded service states', async () => {
    const emptyFetch = vi.fn().mockResolvedValueOnce(statusResponse()).mockResolvedValueOnce(overviewResponse({
      status: 'empty',
      counts: { idea_records: 0, person_records: 0, asset_records: 0, report_version_records: 0 },
      recent: [],
    }));
    await expect(createLocalDashboardClient({ fetchImpl: emptyFetch, location: localLocation }).getSnapshot())
      .resolves.toMatchObject({ state: 'running', latest: [], counts: { Idea: 0 } });

    const stoppedFetch = vi.fn().mockResolvedValueOnce(statusResponse({ services: { database: 'stopped', api: 'stopped', tunnel: 'stopped' } }));
    const stopped = await createLocalDashboardClient({ fetchImpl: stoppedFetch, location: localLocation }).getSnapshot();
    expect(stopped.state).toBe('stopped');
    expect(stoppedFetch).toHaveBeenCalledOnce();

    const explicitStopFetch = vi.fn().mockResolvedValueOnce(statusResponse({
      services: { database: 'stopped', api: 'unavailable', tunnel: 'stopped', intent: 'stopped' },
    }));
    await expect(createLocalDashboardClient({ fetchImpl: explicitStopFetch, location: localLocation }).getSnapshot())
      .resolves.toMatchObject({ state: 'stopped', services: { api: 'unavailable' } });
    expect(explicitStopFetch).toHaveBeenCalledOnce();

    const degradedFetch = vi.fn()
      .mockResolvedValueOnce(statusResponse({ services: { database: 'running', api: 'starting', tunnel: 'unavailable' } }))
      .mockResolvedValueOnce(overviewResponse());
    await expect(createLocalDashboardClient({ fetchImpl: degradedFetch, location: localLocation }).getSnapshot())
      .resolves.toMatchObject({ state: 'degraded', services: { api: 'starting', tunnel: 'unavailable' } });
  });

  it('treats status transport errors as error and overview failures as degraded', async () => {
    const statusFailure = createLocalDashboardClient({
      fetchImpl: async () => { throw new Error('private transport detail'); },
      location: localLocation,
    });
    await expect(statusFailure.getSnapshot()).rejects.toEqual(expect.objectContaining({
      name: 'LocalDashboardClientError', kind: 'unavailable',
    }));

    const overviewFailure = vi.fn().mockResolvedValueOnce(statusResponse()).mockResolvedValueOnce(jsonResponse({ detail: 'private' }, 503));
    await expect(createLocalDashboardClient({ fetchImpl: overviewFailure, location: localLocation }).getSnapshot())
      .resolves.toMatchObject({ state: 'degraded', counts: { Idea: 0 }, latest: [] });

    const malformedOverview = vi.fn().mockResolvedValueOnce(statusResponse()).mockResolvedValueOnce(overviewResponse({ count_basis: 'canonical_concepts' }));
    await expect(createLocalDashboardClient({ fetchImpl: malformedOverview, location: localLocation }).getSnapshot())
      .resolves.toMatchObject({ state: 'degraded' });
  });

  it('fetches fresh CSRF state and a unique idempotency key for each fixed user action', async () => {
    let sequence = 0;
    const fetchImpl = vi.fn()
      .mockResolvedValueOnce(statusResponse())
      .mockResolvedValueOnce(jsonResponse({ action: 'start', status: 'completed' }))
      .mockResolvedValueOnce(statusResponse())
      .mockResolvedValueOnce(jsonResponse({ action: 'stop', status: 'completed' }));
    const client = createLocalDashboardClient({
      fetchImpl,
      location: localLocation,
      createIdempotencyKey: () => `user-action-${++sequence}`,
    });
    const controller = new AbortController();

    await client.start({ signal: controller.signal });
    await client.stop({ signal: controller.signal });

    expect(fetchImpl.mock.calls.map(([path]) => path)).toEqual([
      '/api/status', '/api/control/start', '/api/status', '/api/control/stop',
    ]);
    expect(fetchImpl.mock.calls[1][1]).toEqual(expect.objectContaining({
      method: 'POST',
      signal: controller.signal,
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': 'csrf-from-status',
        'Idempotency-Key': 'user-action-1',
      },
      body: JSON.stringify({ action: 'start' }),
    }));
    expect(fetchImpl.mock.calls[3][1].headers['Idempotency-Key']).toBe('user-action-2');
    expect(fetchImpl.mock.calls[3][1].body).toBe(JSON.stringify({ action: 'stop' }));
    for (const [, options] of fetchImpl.mock.calls) expect(options.headers).not.toHaveProperty('Authorization');
  });

  it('refuses non-local origins, redirects, failed actions, and malformed status', async () => {
    for (const location of [
      { origin: 'https://example.test', hostname: 'example.test' },
      { origin: 'http://sub.localhost:4173', hostname: 'sub.localhost' },
    ]) {
      expect(() => createLocalDashboardClient({ location })).toThrow('exact localhost origin');
    }

    const redirected = createLocalDashboardClient({
      location: localLocation,
      fetchImpl: async () => ({ ...jsonResponse({}), url: 'http://attacker.test/api/status' }),
    });
    await expect(redirected.getSnapshot()).rejects.toBeInstanceOf(LocalDashboardClientError);

    const failedActionFetch = vi.fn()
      .mockResolvedValueOnce(statusResponse())
      .mockResolvedValueOnce(jsonResponse({ action: 'start', status: 'partial_failure' }));
    await expect(createLocalDashboardClient({ fetchImpl: failedActionFetch, location: localLocation }).start())
      .rejects.toBeInstanceOf(LocalDashboardClientError);

    const malformedStatus = createLocalDashboardClient({ fetchImpl: async () => jsonResponse({ controller: 'stopped' }), location: localLocation });
    await expect(malformedStatus.getSnapshot()).rejects.toBeInstanceOf(LocalDashboardClientError);
  });

  it('propagates AbortSignal cancellation', async () => {
    const fetchImpl = vi.fn(async (_path, { signal }) => new Promise((_, reject) => {
      signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true });
    }));
    const client = createLocalDashboardClient({ fetchImpl, location: localLocation });
    const controller = new AbortController();
    const pending = client.getSnapshot({ signal: controller.signal });
    controller.abort();
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
  });
});
