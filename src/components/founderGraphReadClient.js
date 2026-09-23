const READ_PATH = '/v1/founder-graph/mcp/read/search';
const LOCAL_HOSTS = new Set(['127.0.0.1', 'localhost', '[::1]']);

export class FounderGraphReadClientError extends Error {
  constructor(kind) {
    super(kind === 'unavailable' ? 'Founder Graph is unavailable.' : 'Founder Graph could not be loaded.');
    this.name = 'FounderGraphReadClientError';
    this.kind = kind;
  }
}

function requiredText(value, name) {
  if (typeof value !== 'string' || !value.trim()) throw new TypeError(`${name} is required.`);
  return value.trim();
}

function localReadUrl(baseUrl) {
  if (baseUrl == null || baseUrl === '') return READ_PATH;
  const parsed = new URL(requiredText(baseUrl, 'baseUrl'));
  if (!LOCAL_HOSTS.has(parsed.hostname) || parsed.username || parsed.password) {
    throw new TypeError('baseUrl must point to the local Dots service.');
  }
  return new URL(READ_PATH, parsed).toString();
}

async function responseBody(response) {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

/**
 * Creates the one small browser boundary for the already-existing local read
 * route.  The caller deliberately supplies the local owner and any base URL;
 * this module does not discover services or keep credentials.
 */
export function createFounderGraphReadClient({ ownerId, baseUrl = '', fetchImpl = globalThis.fetch } = {}) {
  const localOwnerId = requiredText(ownerId, 'ownerId');
  const url = localReadUrl(baseUrl);
  if (typeof fetchImpl !== 'function') throw new TypeError('fetchImpl must be a function.');

  return Object.freeze({
    async search(query, { signal } = {}) {
      const searchQuery = requiredText(query, 'query');
      if (searchQuery.length > 512) throw new TypeError('query must be at most 512 characters.');

      let response;
      try {
        response = await fetchImpl(url, {
          method: 'POST',
          credentials: 'same-origin',
          signal,
          headers: {
            'Content-Type': 'application/json',
            'X-Local-Owner-Id': localOwnerId,
          },
          body: JSON.stringify({ query: searchQuery, limit: 20 }),
        });
      } catch (error) {
        if (error?.name === 'AbortError') throw error;
        throw new FounderGraphReadClientError('unavailable');
      }

      if (!response || typeof response.ok !== 'boolean') throw new FounderGraphReadClientError('error');
      const body = await responseBody(response);
      if (!response.ok) {
        const code = body?.detail?.code;
        throw new FounderGraphReadClientError(response.status === 503 || code === 'unavailable' ? 'unavailable' : 'error');
      }
      if (!body || !Array.isArray(body.results)) throw new FounderGraphReadClientError('error');
      return body.results;
    },
  });
}
