// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import axe from 'axe-core';
import { afterEach, expect, it, vi } from 'vitest';
import { App } from './App';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let mounted;

afterEach(async () => {
  if (mounted) await act(async () => { mounted.root.unmount(); mounted.container.remove(); });
  mounted = null;
  vi.unstubAllGlobals();
});

it('keeps the current three-screen desktop entrance accessible', async () => {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1280 });
  Object.defineProperty(window, 'innerHeight', { configurable: true, value: 720 });
  vi.stubGlobal('fetch', vi.fn(async (path) => ({
    ok: true,
    status: 200,
    json: async () => path === '/api/status'
      ? { controller: 'running', csrf_token: 'test-only', services: { database: 'running', api: 'running', tunnel: 'running' } }
      : path === '/api/overview'
        ? { status: 'empty', count_basis: 'stored_active_records', counts: { idea_records: 0, person_records: 0, asset_records: 0, report_version_records: 0 }, recent: [] }
        : { status: 'empty', ideas: [], assets: [], profile: null },
  })));
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  mounted = { root, container };
  await act(async () => root.render(<App />));
  expect([...container.querySelectorAll('nav[aria-label="メイン"] button')]).toHaveLength(3);
  expect((await axe.run(container)).violations).toEqual([]);
});
