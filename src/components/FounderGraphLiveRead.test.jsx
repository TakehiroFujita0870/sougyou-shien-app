// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { FounderGraphReadClientError } from './founderGraphReadClient';
import { FounderGraphLiveRead } from './FounderGraphLiveRead';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let root;
let container;

function deferred() {
  let resolve;
  return { promise: new Promise((done) => { resolve = done; }), resolve };
}

async function renderLive(props) {
  container = document.createElement('div');
  document.body.append(container);
  root = createRoot(container);
  await act(async () => root.render(<FounderGraphLiveRead {...props} />));
  return container;
}

afterEach(async () => {
  if (root) await act(async () => root.unmount());
  container?.remove();
  root = undefined;
  container = undefined;
});

describe('FounderGraphLiveRead', () => {
  it('shows loading and then only the returned safe results', async () => {
    const pending = deferred();
    const client = { search: () => pending.promise };
    const view = await renderLive({ client, query: 'circular material' });

    expect(view.querySelector('[data-founder-graph-state-message="loading"]')).not.toBeNull();
    await act(async () => pending.resolve([{ id: 'idea-1', kind: 'idea', title: '循環素材の仮説', snippet: 'safe snippet', fields: { egress_policy: 'shareable', status: 'active' } }]));

    expect(view.querySelector('[data-founder-graph-state-message="loading"]')).toBeNull();
    expect(view.textContent).toContain('循環素材の仮説');
    expect(view.querySelectorAll('[data-founder-graph-card]')).toHaveLength(1);
  });

  it('shows an empty state when the local read returns no matching data', async () => {
    const view = await renderLive({ client: { search: async () => [] }, query: 'missing' });
    await act(async () => Promise.resolve());

    expect(view.querySelector('[data-founder-graph-state-message="empty"]')).not.toBeNull();
    expect(view.querySelectorAll('[data-founder-graph-card]')).toHaveLength(0);
  });

  it('searches the entered wording only after the local founder submits it', async () => {
    const client = { search: vi.fn(async () => [{ id: 'idea-3', kind: 'idea', title: '検索した仮説', snippet: 'safe search result', fields: { egress_policy: 'shareable', status: 'active' } }]) };
    const view = await renderLive({ client, query: '' });
    const input = view.querySelector('#founder-graph-search');

    expect(input.labels[0].textContent).toContain('保存済みの情報を検索');
    expect(client.search).not.toHaveBeenCalled();
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
      setter.call(input, ' 顧客課題 ');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => view.querySelector('[role="search"]').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
    await act(async () => Promise.resolve());

    expect(client.search).toHaveBeenCalledWith('顧客課題', expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(view.textContent).toContain('検索した仮説');
  });

  it('clears old data and retries after the local service becomes available', async () => {
    let calls = 0;
    const client = {
      search: async () => {
        calls += 1;
        if (calls === 1) throw new FounderGraphReadClientError('unavailable');
        return [{ id: 'idea-2', kind: 'idea', title: '再試行後の仮説', snippet: 'safe retry result', fields: { egress_policy: 'shareable', status: 'active' } }];
      },
    };
    const view = await renderLive({ client, query: 'retry' });
    await act(async () => Promise.resolve());

    expect(view.querySelector('[data-founder-graph-state-message="unavailable"]')).not.toBeNull();
    expect(view.querySelectorAll('[data-founder-graph-card]')).toHaveLength(0);
    await act(async () => view.querySelector('[data-founder-graph-retry="true"]').click());
    await act(async () => Promise.resolve());

    expect(calls).toBe(2);
    expect(view.querySelector('[data-founder-graph-state-message="unavailable"]')).toBeNull();
    expect(view.textContent).toContain('再試行後の仮説');
  });

  it('shows a retryable reading failure without stale data', async () => {
    const view = await renderLive({ client: { search: async () => { throw new Error('bad response'); } }, query: 'broken' });
    await act(async () => Promise.resolve());

    expect(view.querySelector('[data-founder-graph-state-message="error"]')).not.toBeNull();
    expect(view.querySelector('[data-founder-graph-retry="true"]')).not.toBeNull();
    expect(view.querySelectorAll('[data-founder-graph-card]')).toHaveLength(0);
  });
});
