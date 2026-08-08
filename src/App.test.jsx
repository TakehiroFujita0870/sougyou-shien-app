import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { App, WORKSPACE_NAV } from './App';

describe('MVP workspace shell', () => {
  it('prioritizes the first profile interview and exposes every workspace', () => {
    const html = renderToStaticMarkup(<App />);

    expect(html).toContain('aria-modal="true"');
    expect(html).toContain('local / fake モード');
    WORKSPACE_NAV.forEach(({ label }) => expect(html).toContain(`>${label}</button>`));
  });

  it('renders native keyboard-operable navigation with visible focus and current location', () => {
    const html = renderToStaticMarkup(<App />);

    expect(html).toContain('aria-current="page"');
    expect(html).toContain('focus-visible:outline-2');
    expect(html).toContain('type="button"');
  });

  it('does not force fixed stages or gates in the normal app workspace', () => {
    const html = renderToStaticMarkup(<App />);

    expect(html).not.toContain('STAGE GATE');
    expect(html).not.toContain('STAGE 0');
    expect(html).not.toContain('条件を満たすまで次へ進みません');
  });

  it('does not expose AI public-relations functionality in the product workspace', () => {
    const html = renderToStaticMarkup(<App />);

    expect(WORKSPACE_NAV.map(({ id }) => id)).not.toContain('public-relations');
    expect(html).not.toContain('AI広報');
  });
});
