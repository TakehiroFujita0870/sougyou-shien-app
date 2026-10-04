// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import { LocalDashboardShell } from './LocalDashboardShell';
import { readFileSync } from 'node:fs';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let mounted;

it('anchors the shared sky to the viewport and reserves a stable scroll gutter', () => {
  const shellStyles = readFileSync('src/components/LocalDashboardShell.css', 'utf8');
  const sky = shellStyles.match(/\.local-shell__sky\s*\{([^}]+)\}/)[1];
  expect(sky).toContain('position: fixed');
  expect(sky).toContain('left: var(--local-sidebar-width)');
  expect(shellStyles).toMatch(/html:has\(\.local-shell\)\s*\{\s*scrollbar-gutter:\s*stable/);
});

afterEach(async () => {
  if (mounted) await act(async () => { mounted.root.unmount(); mounted.container.remove(); });
  mounted = null;
});

it('keeps the three screen navigation actions accessible and routes page selection', async () => {
  const onSelect = vi.fn();
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  mounted = { root, container };
  await act(async () => root.render(<LocalDashboardShell activePage="local-home" onSelect={onSelect}><p>本文</p></LocalDashboardShell>));

  const navigation = [...container.querySelectorAll('.local-shell__nav button')];
  expect(navigation.map((button) => button.textContent.trim())).toEqual(['⌂ ホーム', '✦ グラフ', '◈ サービス管理']);
  expect(container.querySelector('.local-shell__sidebar')).not.toBeNull();
  expect(navigation[0].getAttribute('aria-current')).toBe('page');
  await act(async () => navigation[1].click());
  expect(onSelect).toHaveBeenCalledWith('graph');
});
