import { describe, expect, it, vi } from 'vitest';
import { FounderGraphReadClientError, createFounderGraphReadClient } from './founderGraphReadClient';

function jsonResponse(body, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

describe('Founder Graph local read client', () => {
  it('uses the existing local read route with an explicit local owner', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse({ results: [{ id: 'idea-1' }] }));
    const client = createFounderGraphReadClient({ ownerId: 'local-owner', baseUrl: 'http://127.0.0.1:8000', fetchImpl });

    await expect(client.search('circular material')).resolves.toEqual([{ id: 'idea-1' }]);
    expect(fetchImpl).toHaveBeenCalledWith('http://127.0.0.1:8000/v1/founder-graph/mcp/read/search', expect.objectContaining({
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-Local-Owner-Id': 'local-owner' },
      body: JSON.stringify({ query: 'circular material', limit: 20 }),
    }));
  });

  it('keeps the browser boundary local and classifies a stopped local service as unavailable', async () => {
    expect(() => createFounderGraphReadClient({ ownerId: 'local-owner', baseUrl: 'https://example.test' })).toThrow('local Dots service');
    const client = createFounderGraphReadClient({
      ownerId: 'local-owner',
      fetchImpl: async () => jsonResponse({ detail: { code: 'unavailable' } }, 503),
    });

    await expect(client.search('idea')).rejects.toEqual(expect.objectContaining({
      name: 'FounderGraphReadClientError',
      kind: 'unavailable',
    }));
  });

  it('does not pass through malformed successful responses', async () => {
    const client = createFounderGraphReadClient({ ownerId: 'local-owner', fetchImpl: async () => jsonResponse({ results: 'not a list' }) });

    await expect(client.search('idea')).rejects.toBeInstanceOf(FounderGraphReadClientError);
  });

  it('treats an invalid browser response as a retryable read failure', async () => {
    const client = createFounderGraphReadClient({ ownerId: 'local-owner', fetchImpl: async () => undefined });

    await expect(client.search('idea')).rejects.toEqual(expect.objectContaining({ kind: 'error' }));
  });
});
