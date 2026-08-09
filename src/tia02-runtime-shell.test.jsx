// @vitest-environment happy-dom
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { App, WORKSPACE_NAV, readSelectedSurface } from './App';
import { SHELL_NAV, WorkspaceShell } from './components/WorkspaceShell';

describe('T-IA-02-R runtime shell contract', () => {
  it('exposes only Home, Project, and Knowledge at the top level', () => {
    expect(WORKSPACE_NAV).toEqual([
      { id: 'home', label: 'ホーム' },
      { id: 'project', label: 'プロジェクト' },
      { id: 'knowledge', label: 'ナレッジ' },
    ]);
    expect(SHELL_NAV).toEqual(WORKSPACE_NAV);
  });

  it('renders the Home conversation surface and composer without duplicate entry points', () => {
    const html = renderToStaticMarkup(<App />);

    expect(html).toContain('Kadode AI');
    expect(html).toContain('Kadode AIへのメッセージ');
    expect(html).not.toContain('Enterで送信、Shift+Enterで改行');
    expect(html).not.toMatch(/local|fake|mock/i);
    expect(html).toContain('data-home-composer="true"');
    expect(html).toContain('data-home-scroll-region="true"');
    expect(html).toContain('overflow-y-auto');
    expect(html).toContain('max-w-[900px]');
    expect(html).toContain('h-[calc(100dvh-4rem)]');
    expect(html).toContain('text-2xl font-semibold tracking-tight');
    expect(html).not.toContain('class="page-title"');
    expect(html).not.toContain('始める前に、');
  });

  it('fails safe to Home and preserves only the selected surface in session storage', () => {
    const storage = { getItem: () => 'knowledge' };
    expect(readSelectedSurface(storage)).toBe('knowledge');
    expect(readSelectedSurface({ getItem: () => 'profile' })).toBe('home');
    expect(readSelectedSurface({ getItem: () => 'not-json-or-user-data' })).toBe('home');
  });

  it('keeps the shell nav accessible with a current page', () => {
    const html = renderToStaticMarkup(<WorkspaceShell activePage="home" onSelect={() => {}}><h1>Home</h1></WorkspaceShell>);
    expect(html).toContain('ホーム');
    expect(html).toContain('プロジェクト');
    expect(html).toContain('ナレッジ');
    expect(html).toContain('aria-current="page"');
  });
});
