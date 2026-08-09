import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { App, WORKSPACE_NAV } from './App';

describe('MVP workspace shell', () => {
  it('prioritizes the first profile interview and exposes every workspace', () => {
    const html = renderToStaticMarkup(<App />);

    expect(html).toContain('aria-modal="true"');
    expect(html).toContain('local / fake モード');
    WORKSPACE_NAV.forEach(({ label }) => expect(html).toContain(label));
  });

  it('renders native keyboard-operable navigation with visible focus and current location', () => {
    const html = renderToStaticMarkup(<App />);

    expect(html).toContain('aria-current="page"');
    expect(html).toContain('workspace-shell__nav-item');
    expect(html).toContain('type="button"');
  });

  it('does not force fixed stages or gates in the normal app workspace', () => {
    const html = renderToStaticMarkup(<App />);

    expect(html).not.toContain('STAGE GATE');
    expect(html).not.toContain('STAGE 0');
    expect(html).not.toContain('条件を満たすまで次へ進みません');
  });

  it('uses a compact idea page instead of a failure-first hero', () => {
    const html = renderToStaticMarkup(<App />);

    expect(html).toContain('着想や経験を話しながら整理し、確認してから候補として保存します。');
    expect(html).not.toContain('sm:text-6xl');
    expect(html).not.toContain('始める前に、');
    expect(html).not.toContain('ダメな理由を見つけよう');
  });

  it('uses one conversation entry instead of the legacy three-field idea form', () => {
    const html = renderToStaticMarkup(<App />);

    expect(html).toContain('アイデアを話してみる');
    expect(html).not.toContain('アイデアを登録する');
    expect(html).not.toContain('誰の、何のペインか');
  });

  it('does not expose AI public-relations functionality in the product workspace', () => {
    const html = renderToStaticMarkup(<App />);

    expect(WORKSPACE_NAV.map(({ id }) => id)).not.toContain('public-relations');
    expect(html).not.toContain('AI広報');
  });

  it('exposes the vertical workspace shell information architecture', () => {
    const html = renderToStaticMarkup(<App />);
    expect(html).toContain('ワークスペースサイドバー');
    expect(html).toContain('Kadode workspace');
    expect(html).toContain('プランを見る');
    expect(html).toContain('ワークスペース');
  });
});
