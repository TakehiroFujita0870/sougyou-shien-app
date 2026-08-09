import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { App, WORKSPACE_NAV } from './App';

describe('Kadode three-surface workspace shell', () => {
  it('exposes Home, Project, and Knowledge as the only top-level surfaces', () => {
    const html = renderToStaticMarkup(<App />);
    expect(WORKSPACE_NAV.map(({ label }) => label)).toEqual(['Home', 'Project', 'Knowledge']);
    WORKSPACE_NAV.forEach(({ label }) => expect(html).toContain(label));
  });

  it('starts Home with one Kadode AI composer and no legacy candidate workflow', () => {
    const html = renderToStaticMarkup(<App />);
    expect(html).toContain('id="home-composer"');
    expect(html).toContain('Kadode AI');
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
