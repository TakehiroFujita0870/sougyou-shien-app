import { LocalDashboardClientError } from './localDashboardClientError.js';
import { projectLocalHome } from './localHomeProjection.js';
import { safePublicCitationUrl } from './publicCitationUrl.js';
export { LocalDashboardClientError } from './localDashboardClientError.js';

const LOCAL_HOSTS = new Set(['localhost', '127.0.0.1', '[::1]']);
const SERVICE_NAMES = ['database', 'api', 'tunnel'];
const COUNT_MAP = {
  idea_records: 'Idea',
  person_records: 'Person',
  asset_records: 'Asset',
  report_version_records: 'ReportVersion',
};
const GRAPH_PROCESSING_STATES = ['pending', 'leased', 'succeeded', 'failed', 'superseded'];
const KIND_MAP = {
  idea: 'Idea',
  person: 'Person',
  asset: 'Asset',
  report_version: 'ReportVersion',
};
const ZERO_COUNTS = { Idea: 0, Person: 0, Asset: 0, ReportVersion: 0 };

function assertLocalOrigin(location) {
  if (!location || typeof location.origin !== 'string' || !LOCAL_HOSTS.has(location.hostname)) {
    throw new TypeError('Local dashboard client requires an exact localhost origin.');
  }
  let origin;
  try {
    origin = new URL(location.origin);
  } catch {
    throw new TypeError('Local dashboard client requires an exact localhost origin.');
  }
  if (!['http:', 'https:'].includes(origin.protocol) || !LOCAL_HOSTS.has(origin.hostname) || origin.origin !== location.origin) {
    throw new TypeError('Local dashboard client requires an exact localhost origin.');
  }
  return origin.origin;
}

function requiredObject(value, kind = 'error') {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new LocalDashboardClientError(kind);
  return value;
}

function normalizedServiceState(value) {
  return ['running', 'stopped', 'starting', 'unavailable'].includes(value) ? value : 'unavailable';
}

function safeCounts(overview) {
  const source = requiredObject(overview.counts, 'degraded');
  const counts = {};
  for (const [apiName, uiName] of Object.entries(COUNT_MAP)) {
    const count = source[apiName];
    if (!Number.isSafeInteger(count) || count < 0) throw new LocalDashboardClientError('degraded');
    counts[uiName] = count;
  }
  return counts;
}

function safeLatest(overview) {
  if (!Array.isArray(overview.recent)) throw new LocalDashboardClientError('degraded');
  return overview.recent.flatMap((item) => {
    if (!item || typeof item !== 'object' || typeof item.id !== 'string' || !item.id) return [];
    const kind = KIND_MAP[item.kind];
    if (!kind) return [];
    if (kind === 'ReportVersion') return [{ id: item.id, kind, title: '調査レポート' }];
    // The backend has already projected Idea.title and Person/Asset.name into
    // one allowlisted `title` field. Do not inspect arbitrary payload fields.
    const titleField = kind === 'Idea' ? 'title' : 'name';
    const title = item.title;
    if (typeof title !== 'string' || !title.trim()) return [];
    return [{ id: item.id, kind, [titleField]: title.trim() }];
  });
}

function safeGraphProcessing(payload) {
  if (payload.status === 'unavailable' || payload.status === 'failed') return { status: 'unavailable' };
  if (payload.status !== 'ready') throw new LocalDashboardClientError('error');
  const source = requiredObject(payload.counts);
  const counts = {};
  for (const state of GRAPH_PROCESSING_STATES) {
    if (!Number.isSafeInteger(source[state]) || source[state] < 0) throw new LocalDashboardClientError('error');
    counts[state] = source[state];
  }
  return { status: 'ready', counts };
}

function snapshotState(services, overviewStatus) {
  const values = SERVICE_NAMES.map((name) => services[name]);
  if (values.every((status) => status === 'stopped')) return 'stopped';
  if (values.every((status) => status === 'running') && ['ready', 'empty'].includes(overviewStatus)) return 'running';
  return 'degraded';
}

function defaultIdempotencyKey(cryptoImpl) {
  if (typeof cryptoImpl?.randomUUID !== 'function') throw new LocalDashboardClientError('error');
  return cryptoImpl.randomUUID();
}

/** Create a same-origin browser client for the fixed local controller API. */
export function createLocalDashboardClient({
  fetchImpl = globalThis.fetch,
  location = globalThis.location,
  cryptoImpl = globalThis.crypto,
  createIdempotencyKey = () => defaultIdempotencyKey(cryptoImpl),
} = {}) {
  const origin = assertLocalOrigin(location);
  if (typeof fetchImpl !== 'function') throw new TypeError('fetch must be available.');
  const assetWriteIntents = new Map();
  const ideaWriteIntents = new Map();
  const recordLifecycleIntents = new Map();

  async function request(path, { method = 'GET', signal, headers = {}, body } = {}) {
    let response;
    try {
      response = await fetchImpl(path, {
        method,
        credentials: 'same-origin',
        mode: 'same-origin',
        redirect: 'error',
        referrerPolicy: 'no-referrer',
        signal,
        headers,
        ...(body === undefined ? {} : { body }),
      });
    } catch (error) {
      if (error?.name === 'AbortError') throw error;
      throw new LocalDashboardClientError('unavailable');
    }
    if (!response || typeof response.ok !== 'boolean') throw new LocalDashboardClientError('error');
    if (response.url) {
      try {
        if (new URL(response.url, origin).origin !== origin) throw new LocalDashboardClientError('error');
      } catch (error) {
        if (error instanceof LocalDashboardClientError) throw error;
        throw new LocalDashboardClientError('error');
      }
    }
    let payload;
    try {
      payload = await response.json();
    } catch {
      throw new LocalDashboardClientError(response.status === 503 ? 'unavailable' : 'error');
    }
    if (!response.ok) throw new LocalDashboardClientError(response.status === 409 ? 'conflict' : response.status === 503 ? 'unavailable' : 'error');
    return requiredObject(payload);
  }

  async function readStatus(signal) {
    const status = await request('/api/status', { signal });
    if (status.controller !== 'running' || typeof status.csrf_token !== 'string' || !status.csrf_token) {
      throw new LocalDashboardClientError('error');
    }
    const rawServices = requiredObject(status.services);
    const services = Object.fromEntries(SERVICE_NAMES.map((name) => [name, normalizedServiceState(rawServices[name])]));
    const stopIntent = normalizedServiceState(rawServices.intent);
    return { csrfToken: status.csrf_token, services, stopIntent };
  }

  async function getSnapshot({ signal } = {}) {
    const { services, stopIntent } = await readStatus(signal);
    const explicitlyStopped = stopIntent === 'stopped'
      && services.database === 'stopped'
      && services.tunnel === 'stopped'
      && ['stopped', 'unavailable'].includes(services.api);
    if (explicitlyStopped || SERVICE_NAMES.every((name) => services[name] === 'stopped')) {
      return { state: 'stopped', services, counts: { ...ZERO_COUNTS }, latest: [], countBasis: 'stored_active_records' };
    }

    try {
      const overview = await request('/api/overview', { signal });
      if (signal?.aborted) throw new DOMException('The operation was aborted.', 'AbortError');
      if (overview.count_basis !== 'stored_active_records') throw new LocalDashboardClientError('degraded');
      const counts = safeCounts(overview);
      const latest = safeLatest(overview);
      const state = snapshotState(services, overview.status);
      return { state, services, counts, latest, countBasis: 'stored_active_records' };
    } catch (error) {
      if (signal?.aborted || error?.name === 'AbortError') throw error;
      return { state: 'degraded', services, counts: { ...ZERO_COUNTS }, latest: [], countBasis: 'stored_active_records' };
    }
  }

  async function getServiceSnapshot({ signal } = {}) {
    const { services, stopIntent } = await readStatus(signal);
    const values = SERVICE_NAMES.map((name) => services[name]);
    const stopped = stopIntent === 'stopped' && services.database === 'stopped' && services.tunnel === 'stopped'
      || values.every((value) => value === 'stopped');
    const state = stopped ? 'stopped' : values.every((value) => value === 'running') ? 'running' : 'degraded';
    let processing = { status: 'unavailable' };
    if (services.database === 'running') {
      try {
        processing = safeGraphProcessing(await request('/api/graph-processing', { signal }));
      } catch (error) {
        if (signal?.aborted || error?.name === 'AbortError') throw error;
      }
    }
    return { state, services, counts: { ...ZERO_COUNTS }, latest: [], countBasis: 'stored_active_records', processing };
  }

  async function getHome({ signal } = {}) {
    const result = await request('/api/home', { signal });
    return projectLocalHome(result);
  }

  async function getGraph({ signal } = {}) {
    const result = await request('/api/graph', { signal });
    if (!['ready', 'empty', 'stopped'].includes(result.status) || !Array.isArray(result.nodes) || !Array.isArray(result.edges) || typeof result.truncated !== 'boolean') {
      throw new LocalDashboardClientError('error');
    }
    const nodes = result.nodes.map((item) => {
      if (!item || typeof item.id !== 'string' || typeof item.kind !== 'string' || typeof item.label !== 'string') throw new LocalDashboardClientError('error');
      const url = item.kind === 'source' ? safePublicCitationUrl(item.url) : null;
      return { id: item.id, kind: item.kind, label: item.label, ...(url ? { url } : {}) };
    });
    const ids = new Set(nodes.map((node) => node.id));
    const edges = result.edges.map((item) => {
      if (!item || !ids.has(item.source) || !ids.has(item.target) || typeof item.label !== 'string') throw new LocalDashboardClientError('error');
      return { source: item.source, target: item.target, label: item.label };
    });
    const rawSemanticEdges = result.semantic_edges ?? [];
    if (!Array.isArray(rawSemanticEdges) || rawSemanticEdges.length > 400) throw new LocalDashboardClientError('error');
    const assertionIds = new Set();
    const semanticEdges = rawSemanticEdges.map((item) => {
      const validId = (value) => typeof value === 'string' && value.trim().length > 0 && value.length <= 512;
      if (!item || !validId(item.id) || assertionIds.has(item.id)
        || !ids.has(item.source_id) || !ids.has(item.target_id)
        || typeof item.predicate !== 'string' || !item.predicate.trim() || item.predicate.length > 60
        || !['proposed', 'inferred', 'confirmed'].includes(item.status)
        || (item.confidence !== null && (!Number.isFinite(item.confidence) || item.confidence < 0 || item.confidence > 1))
        || !Array.isArray(item.evidence_ids) || item.evidence_ids.length > 200 || !item.evidence_ids.every(validId)
        || (item.based_on_brief_id === null) !== (item.based_on_brief_section_index === null)
        || (item.based_on_brief_id !== null && (!validId(item.based_on_brief_id)
          || !Number.isInteger(item.based_on_brief_section_index) || item.based_on_brief_section_index < 0 || item.based_on_brief_section_index > 7))) {
        throw new LocalDashboardClientError('error');
      }
      assertionIds.add(item.id);
      return { id: item.id, source_id: item.source_id, target_id: item.target_id,
        predicate: item.predicate, status: item.status, confidence: item.confidence,
        evidence_ids: [...new Set(item.evidence_ids)], based_on_brief_id: item.based_on_brief_id,
        based_on_brief_section_index: item.based_on_brief_section_index };
    });
    return { status: result.status, nodes, edges, semantic_edges: semanticEdges, truncated: result.truncated };
  }

  async function getSemanticEdgeProvenance(assertionId, { signal } = {}) {
    const validId = (value) => typeof value === 'string' && value.trim().length > 0 && value.length <= 512;
    if (!validId(assertionId)) throw new LocalDashboardClientError('error');
    const result = await request(`/api/graph/semantic-edges/${encodeURIComponent(assertionId)}/provenance`, { signal });
    if (result.status === 'stopped') {
      if (result.assertion_id !== undefined && result.assertion_id !== assertionId) throw new LocalDashboardClientError('error');
      return { status: 'stopped' };
    }
    if (result.status !== 'ready' || result.assertion_id !== assertionId
      || (result.section !== null && (!result.section || typeof result.section !== 'object' || Array.isArray(result.section)))
      || !Array.isArray(result.evidence) || result.evidence.length > 200) {
      throw new LocalDashboardClientError('error');
    }
    let section = null;
    if (result.section !== null) {
      const item = result.section;
      if (!validId(item.brief_id) || !Number.isSafeInteger(item.revision) || item.revision < 1
        || !validId(item.idea_id) || !Number.isInteger(item.section_index) || item.section_index < 0 || item.section_index > 7
        || typeof item.title !== 'string' || !item.title.trim() || item.title.length > 200
        || typeof item.content !== 'string' || !item.content.trim() || item.content.length > 16000) {
        throw new LocalDashboardClientError('error');
      }
      section = {
        brief_id: item.brief_id,
        revision: item.revision,
        idea_id: item.idea_id,
        section_index: item.section_index,
        title: item.title.trim(),
        content: item.content,
      };
    }
    const evidenceIds = new Set();
    const evidence = result.evidence.map((item) => {
      if (!item || !validId(item.id) || evidenceIds.has(item.id)
        || !['supports', 'contradicts', 'neutral'].includes(item.polarity)
        || !Number.isFinite(item.confidence) || item.confidence < 0 || item.confidence > 1
        || item.status !== 'active') {
        throw new LocalDashboardClientError('error');
      }
      evidenceIds.add(item.id);
      return { id: item.id, polarity: item.polarity, confidence: item.confidence, status: item.status };
    });
    return { status: 'ready', assertion_id: assertionId, section, evidence };
  }

  async function getFacetRegion(facetId, depth, { signal } = {}) {
    if (typeof facetId !== 'string' || !facetId.trim() || !Number.isInteger(depth) || depth < 0 || depth > 3) {
      throw new LocalDashboardClientError('error');
    }
    const result = await request(`/api/graph/facet-region?facet_id=${encodeURIComponent(facetId)}&depth=${depth}`, { signal });
    if (!['ready', 'empty', 'stopped'].includes(result.status) || result.facet_id !== facetId || result.depth !== depth || !Array.isArray(result.hits)) {
      throw new LocalDashboardClientError('error');
    }
    const seen = new Set();
    const hits = result.hits.map((item) => {
      const facetPath = item?.facet_path;
      const membershipKey = item && typeof item.id === 'string' && typeof item.matched_facet_id === 'string'
        ? JSON.stringify([item.id, item.matched_facet_id])
        : '';
      if (!item || typeof item.id !== 'string' || !item.id || !membershipKey || seen.has(membershipKey)
        || !['idea', 'asset'].includes(item.kind) || typeof item.title !== 'string'
        || !item.title.trim() || item.root_facet_id !== facetId
        || typeof item.matched_facet_id !== 'string' || !item.matched_facet_id
        || !Number.isInteger(item.depth) || item.depth < 0 || item.depth > depth
        || !['inferred', 'confirmed'].includes(item.classification_status)
        || !Array.isArray(item.classification_evidence_ids) || !item.classification_evidence_ids.length
        || item.classification_evidence_ids.some((id) => typeof id !== 'string' || !id)
        || !Array.isArray(item.taxonomy_status_path) || item.taxonomy_status_path.length !== item.depth
        || item.taxonomy_status_path.some((status) => !['inferred', 'confirmed'].includes(status))
        || !Array.isArray(item.taxonomy_evidence_path) || item.taxonomy_evidence_path.length !== item.depth
        || item.taxonomy_evidence_path.some((path) => !Array.isArray(path) || !path.length || path.some((id) => typeof id !== 'string' || !id))
        || !Array.isArray(facetPath) || facetPath.length !== item.depth + 1
        || facetPath[0]?.facet_id !== facetId || facetPath.at(-1)?.facet_id !== item.matched_facet_id
        || facetPath.some((entry, index) => !entry || typeof entry.facet_id !== 'string' || !entry.facet_id.trim()
          || entry.facet_id.length > 512 || typeof entry.label !== 'string' || !entry.label.trim()
          || entry.label.length > 512 || entry.depth !== index)
        || new Set(facetPath.map((entry) => entry?.facet_id)).size !== facetPath.length
        || !Array.isArray(item.evidence_ids) || !item.evidence_ids.length
        || item.evidence_ids.some((id) => typeof id !== 'string' || !id)
        || [...item.classification_evidence_ids, ...item.taxonomy_evidence_path.flat()].some((id) => !item.evidence_ids.includes(id))) {
        throw new LocalDashboardClientError('error');
      }
      seen.add(membershipKey);
      return {
        id: item.id,
        kind: item.kind,
        title: item.title.trim(),
        root_facet_id: item.root_facet_id,
        matched_facet_id: item.matched_facet_id,
        depth: item.depth,
        classification_status: item.classification_status,
        classification_evidence_ids: [...item.classification_evidence_ids],
        taxonomy_status_path: [...item.taxonomy_status_path],
        taxonomy_evidence_path: item.taxonomy_evidence_path.map((path) => [...path]),
        facet_path: facetPath.map((entry) => ({
          facet_id: entry.facet_id,
          label: entry.label.trim(),
          depth: entry.depth,
        })),
        evidence_ids: [...new Set(item.evidence_ids)],
      };
    });
    return { status: result.status, facet_id: facetId, depth, hits };
  }

  async function saveAsset(assetId, { name, description, expectedRevision, kind } = {}, { signal } = {}) {
    if (typeof assetId !== 'string' || !assetId || typeof name !== 'string' || !name.trim() || name.trim().length > 200
      || typeof description !== 'string' || description.length > 4000 || !Number.isSafeInteger(expectedRevision) || expectedRevision < 1
      || (kind !== undefined && !['strength', 'barrier'].includes(kind))) {
      throw new LocalDashboardClientError('error');
    }
    const normalizedName = name.trim();
    const intent = JSON.stringify([normalizedName, description, expectedRevision, kind]);
    let write = assetWriteIntents.get(assetId);
    if (!write || write.intent !== intent) {
      const idempotencyKey = createIdempotencyKey();
      if (typeof idempotencyKey !== 'string' || !idempotencyKey.trim() || idempotencyKey.length > 128) throw new LocalDashboardClientError('error');
      write = { intent, idempotencyKey };
      assetWriteIntents.set(assetId, write);
    }
    const { csrfToken } = await readStatus(signal);
    const result = await request(`/api/assets/${encodeURIComponent(assetId)}`, {
      method: 'PUT', signal,
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
      body: JSON.stringify({
        name: normalizedName,
        description,
        expected_revision: expectedRevision,
        idempotency_key: write.idempotencyKey,
        ...(kind === undefined ? {} : { kind }),
      }),
    });
    if (typeof result.id !== 'string' || !result.id || !Number.isSafeInteger(result.revision) || result.revision !== expectedRevision + 1) {
      throw new LocalDashboardClientError('error');
    }
    return { id: result.id, revision: result.revision };
  }

  async function saveIdea(ideaId, { title, description, expectedRevision } = {}, { signal } = {}) {
    if (typeof ideaId !== 'string' || !ideaId || typeof title !== 'string' || !title.trim() || title.trim().length > 200
      || typeof description !== 'string' || description.length > 4000 || !Number.isSafeInteger(expectedRevision) || expectedRevision < 0) {
      throw new LocalDashboardClientError('error');
    }
    const normalizedTitle = title.trim();
    const intent = JSON.stringify([normalizedTitle, description, expectedRevision]);
    let write = ideaWriteIntents.get(ideaId);
    if (!write || write.intent !== intent) {
      const idempotencyKey = createIdempotencyKey();
      if (typeof idempotencyKey !== 'string' || !idempotencyKey.trim() || idempotencyKey.length > 128) throw new LocalDashboardClientError('error');
      write = { intent, idempotencyKey };
      ideaWriteIntents.set(ideaId, write);
    }
    const { csrfToken } = await readStatus(signal);
    const result = await request(`/api/ideas/${encodeURIComponent(ideaId)}`, {
      method: 'PUT', signal,
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
      body: JSON.stringify({
        title: normalizedTitle,
        description,
        expected_revision: expectedRevision,
        idempotency_key: write.idempotencyKey,
      }),
    });
    if (typeof result.id !== 'string' || !result.id || !Number.isSafeInteger(result.revision) || result.revision !== expectedRevision + 1) {
      throw new LocalDashboardClientError('error');
    }
    return { id: result.id, revision: result.revision };
  }

  async function getDeletedRecords({ signal } = {}) {
    const result = await request('/api/deleted-records', { signal });
    if (!['ready', 'empty', 'stopped', 'failed'].includes(result.status) || !Array.isArray(result.records)) throw new LocalDashboardClientError('error');
    const seen = new Set();
    const records = result.records.map((item) => {
      if (!item || !['idea', 'asset'].includes(item.kind) || typeof item.id !== 'string' || !item.id
        || typeof item.title !== 'string' || typeof item.description !== 'string'
        || !Number.isSafeInteger(item.revision) || item.revision < (item.kind === 'idea' ? 0 : 1)) throw new LocalDashboardClientError('error');
      const key = JSON.stringify([item.kind, item.id]);
      if (seen.has(key)) throw new LocalDashboardClientError('error');
      seen.add(key);
      return { id: item.id, kind: item.kind, title: item.title, description: item.description, revision: item.revision };
    });
    return { status: result.status, records };
  }

  async function changeRecordStatus(action, kind, id, expectedRevision, { signal } = {}) {
    if (!['idea', 'asset'].includes(kind) || typeof id !== 'string' || !id.trim() || id.length > 512
      || !Number.isSafeInteger(expectedRevision) || expectedRevision >= Number.MAX_SAFE_INTEGER || expectedRevision < (kind === 'idea' ? 0 : 1)) throw new LocalDashboardClientError('error');
    const intent = JSON.stringify([action, kind, id, expectedRevision]);
    let key = recordLifecycleIntents.get(intent);
    if (!key) {
      key = createIdempotencyKey();
      if (typeof key !== 'string' || !key.trim() || key.length > 128) throw new LocalDashboardClientError('error');
      recordLifecycleIntents.set(intent, key);
    }
    const { csrfToken } = await readStatus(signal);
    const result = await request(`/api/records/${kind}/${encodeURIComponent(id)}/${action}`, {
      method: 'POST', signal,
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
      body: JSON.stringify({ expected_revision: expectedRevision, idempotency_key: key }),
    });
    if (typeof result.id !== 'string' || !result.id || !Number.isSafeInteger(result.revision) || result.revision !== expectedRevision + 1 || typeof result.replayed !== 'boolean') throw new LocalDashboardClientError('error');
    return { id: result.id, revision: result.revision, replayed: result.replayed };
  }

  async function operate(action, { signal } = {}) {
    const { csrfToken } = await readStatus(signal);
    const idempotencyKey = createIdempotencyKey();
    if (typeof idempotencyKey !== 'string' || !idempotencyKey.trim() || idempotencyKey.length > 128) {
      throw new LocalDashboardClientError('error');
    }
    const result = await request(`/api/control/${action}`, {
      method: 'POST',
      signal,
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': csrfToken,
        'Idempotency-Key': idempotencyKey,
      },
      body: JSON.stringify({ action }),
    });
    if (result.action !== action || result.status !== 'completed') throw new LocalDashboardClientError('error');
    return result;
  }

  return Object.freeze({
    getSnapshot,
    getServiceSnapshot,
    getHome,
    getGraph,
    getSemanticEdgeProvenance,
    getFacetRegion,
    saveAsset,
    saveIdea,
    getDeletedRecords,
    archiveRecord: (kind, id, revision, options) => changeRecordStatus('archive', kind, id, revision, options),
    restoreRecord: (kind, id, revision, options) => changeRecordStatus('restore', kind, id, revision, options),
    start: (options) => operate('start', options),
    stop: (options) => operate('stop', options),
  });
}
