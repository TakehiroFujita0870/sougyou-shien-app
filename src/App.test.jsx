import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { App, WORKSPACE_NAV } from './App';

describe('Kadode three-surface workspace shell', () => {
  it('exposes Home, Project, and Knowledge as the only top-level surfaces', () => {
    const html = renderToStaticMarkup(<App />);
    expect(WORKSPACE_NAV.map(({ label }) => label)).toEqual(['Home', 'Project', 'Knowledge']);
    WORKSPACE_NAV.forEach(({ label }) => expect(html).toContain(label));
    expect(html).not.toContain('AIチャット');
    expect(html).not.toContain('事業のタネ');
    expect(html).not.toContain('横断調査');
    expect(html).not.toContain('資料');
    expect(html).not.toContain('検索');
  });

  it('starts Home with one Kadode AI composer and no legacy candidate workflow', () => {
    const html = renderToStaticMarkup(<App />);
    expect(html).toContain('id="home-composer"');
    expect(html).toContain('Kadode AI');
    expect(html).not.toContain('id="idea-message"');
    expect(html).not.toContain('アイデア候補として保存');
    expect(html).not.toContain('アイデアを登録する');
    expect(html).not.toContain('STAGE GATE');
  });

  it('keeps the Home composer accessible and independent of external services', () => {
    const html = renderToStaticMarkup(<App />);
    expect(html).toContain('label for="home-composer"');
    expect(html).toContain('aria-describedby="home-composer-hint"');
    expect(html).toContain('Enterで送信、Shift+Enterで改行');
    expect(html).not.toContain('fetch(');
    expect(html).not.toContain('AI広報');
  });
});
