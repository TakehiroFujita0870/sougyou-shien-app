// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;


function jsonResponse(body) {
  return { ok: true, status: 200, json: async () => body };
}

function installLocalDashboardEnvironment() {
  vi.stubGlobal('location', { protocol: 'http:', hostname: 'localhost', port: '8765', origin: 'http://localhost:8765' });
  vi.stubGlobal('fetch', vi.fn(async (path) => {
    if (path === '/api/status') return jsonResponse({ controller: 'running', csrf_token: 'csrf', services: { database: 'running', api: 'running', tunnel: 'running' } });
    if (path === '/api/overview') return jsonResponse({ status: 'empty', count_basis: 'stored_active_records', counts: { idea_records: 0, person_records: 0, asset_records: 0, report_version_records: 0 }, recent: [] });
    if (path === '/api/home') return jsonResponse({ status: 'empty', ideas: [], assets: [], profile: null });
    if (path === '/api/graph') return jsonResponse({ status: 'empty', nodes: [], edges: [], truncated: false });
    if (path === '/v1/founder-graph/mcp/read/search') return jsonResponse({ results: [] });
    throw new Error('Unexpected endpoint');
  }));
}

function mountApp() {
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  return {
    container,
    render: () => act(async () => root.render(<App />)),
    unmount: () => act(() => { root.unmount(); container.remove(); }),
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.removeItem('dots:selected-surface');
});

describe('localhost dashboard app integration', () => {
  it('uses the approved three-screen starfield shell', async () => {
    installLocalDashboardEnvironment();
    const app = mountApp();
    await app.render();

    expect(app.container.querySelector('h1#local-home-heading')?.classList.contains('sr-only')).toBe(true);
    expect(app.container.querySelector('.local-home__header')).toBeNull();
    expect(app.container.querySelector('.local-shell__topbar')).toBeNull();
    expect(app.container.textContent).not.toContain('考えたことと、創業に使える自分の資産を確認できます。');
    const nav = app.container.querySelector('nav[aria-label="メイン"]');
    expect([...nav.querySelectorAll('button')].map((button) => button.textContent.trim())).toEqual(['⌂ ホーム', '✦ グラフ', '◈ サービス管理']);
    expect(nav.querySelector('[aria-current="page"]')?.textContent).toContain('ホーム');
    expect(app.container.querySelector('.local-shell__sky')).toBeTruthy();
    const brand = app.container.querySelector('.local-shell__brand');
    expect(brand?.getAttribute('aria-label')).toBe('Dots.');
    expect(brand.querySelector('svg')).toBeNull();
    expect([...brand.querySelectorAll('img')].map((image) => image.getAttribute('src'))).toEqual([
      expect.stringMatching(/dots-icon.*\.png$/),
      expect.stringMatching(/dots-icon.*\.png$/),
    ]);
    expect(globalThis.fetch.mock.calls.map(([path]) => path)).toEqual(['/api/home']);
    await app.unmount();
  });

  it('opens the Neo4j-only graph and service management as separate screens', async () => {
    installLocalDashboardEnvironment();
    const app = mountApp();
    await app.render();

    const nav = app.container.querySelector('nav[aria-label="メイン"]');
    await act(async () => nav.querySelectorAll('button')[1].click());
    expect(nav.querySelector('[aria-current="page"]')?.textContent).toContain('グラフ');
    expect(app.container.querySelector('#local-graph-heading')).toBeTruthy();
    expect(app.container.querySelector('#local-graph-heading').classList.contains('sr-only')).toBe(true);
    expect(app.container.querySelector('.local-graph header')).toBeNull();
    expect(app.container.querySelector('[role="tablist"]')).toBeNull();
    expect(globalThis.fetch.mock.calls.some(([path]) => path === '/api/graph')).toBe(true);
    await act(async () => nav.querySelectorAll('button')[2].click());
    expect(app.container.querySelector('#local-control-heading')?.textContent).toBe('サービス管理');
    expect(app.container.querySelector('#local-control-heading')?.classList.contains('sr-only')).toBe(true);
    expect(app.container.textContent).not.toContain('Dots. ローカル操作盤');
    expect(globalThis.fetch.mock.calls.some(([path]) => path === '/api/status')).toBe(true);
    await app.unmount();
  });

});
