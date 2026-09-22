import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { App, WORKSPACE_NAV } from './App';

describe('Dots. three-surface workspace shell', () => {
  it('exposes Home, Project, and Knowledge as the only top-level surfaces', () => {
    const html = renderToStaticMarkup(<App />);
    expect(WORKSPACE_NAV.map(({ label }) => label)).toEqual(['ホーム', 'プロジェクト', 'ナレッジ']);
    WORKSPACE_NAV.forEach(({ label }) => expect(html).toContain(label));
  });

  it('starts Home with the reachable Dots. AI candidate composer', () => {
    const html = renderToStaticMarkup(<App />);
    expect(html).toContain('id="home-supervisor-message"');
    expect(html).toContain('Dots. AI');
    expect(html).not.toContain('STAGE GATE');
    expect(html).not.toContain('現場で見つかった改善の芽を、低リスク');
  });

  it('keeps the Home composer accessible and independent of external services', () => {
    const html = renderToStaticMarkup(<App />);
    expect(html).toContain('for="home-supervisor-message"');
    expect(html).toContain('GPT-5.6 Terra');
    expect(html).not.toContain('Enterで送信、Shift+Enterで改行');
    expect(html).not.toContain('fetch(');
    expect(html).not.toContain('AI広報');
  });
});
