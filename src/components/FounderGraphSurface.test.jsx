// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it } from 'vitest';
import { FounderGraphSurface } from './FounderGraphSurface';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const results = [
  {
    id: 'idea-1',
    kind: 'idea',
    title: '循環素材の事業仮説',
    snippet: '製造現場の廃材を再利用する仮説',
    fields: { egress_policy: 'shareable', status: 'active', summary: '市場仮説の要約' },
    relation_path: ['person-1', 'can_contribute_to', 'idea-1'],
  },
  {
    id: 'asset-1',
    kind: 'asset',
    title: '顧客ヒアリングメモ',
    snippet: '検証に使う合成メモ',
    fields: { egress_policy: 'shareable', status: 'ready', kind: 'note' },
  },
  {
    id: 'source-1',
    kind: 'source',
    title: '公開統計の出典',
    snippet: '公開された統計への参照',
    fields: { egress_policy: 'shareable', status: 'current', locator: 'p. 4' },
  },
  {
    id: 'person-1',
    kind: 'person',
    title: '協力候補者',
    snippet: '事業仮説に関係する人物',
    fields: { egress_policy: 'shareable', status: 'active', description: '協力領域' },
  },
];

const previousReport = {
  id: 'report-previous',
  status: 'draft',
  sections: [{ id: 0, content: '前版の要約' }],
};

const currentReport = {
  id: 'report-current',
  status: 'final',
  sections: [{ id: 0, content: '現版の要約' }],
};

let root;
let container;

afterEach(() => {
  if (root) act(() => root.unmount());
  container?.remove();
  root = undefined;
  container = undefined;
});

function renderSurface(props = {}) {
  container = document.createElement('div');
  document.body.append(container);
  root = createRoot(container);
  act(() => root.render(<FounderGraphSurface results={results} {...props} />));
  return container;
}

describe('FounderGraphSurface', () => {
  it('switches the four graph categories with tabs and arrow keys', () => {
    const view = renderSurface();
    const tabs = [...view.querySelectorAll('[role="tab"]')];

    expect(tabs.map((tab) => tab.textContent)).toEqual(['Ideas', 'Assets', 'Sources', 'People']);
    expect(tabs[0].getAttribute('aria-selected')).toBe('true');
    expect(view.querySelectorAll('[data-founder-graph-card]')).toHaveLength(1);
    expect(view.textContent).toContain('循環素材の事業仮説');
    expect(view.textContent).not.toContain('顧客ヒアリングメモ');

    act(() => tabs[0].dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, cancelable: true })));

    expect(tabs[1].getAttribute('aria-selected')).toBe('true');
    expect(view.querySelectorAll('[data-founder-graph-card]')).toHaveLength(1);
    expect(view.textContent).toContain('顧客ヒアリングメモ');
    expect(view.textContent).not.toContain('循環素材の事業仮説');
  });

  it('shows safe node details after activation without rendering private or raw fields', () => {
    const view = renderSurface({
      results: [
        {
          ...results[0],
          text: 'local-only raw content',
          fields: {
            ...results[0].fields,
            contact: { email: 'private@example.test' },
            private_notes: 'do not render this',
            source_text: 'raw source text',
            content: 'raw content',
          },
        },
      ],
    });
    const card = view.querySelector('[data-founder-graph-card]');

    act(() => card.click());

    expect(view.querySelector('[data-founder-graph-detail]').textContent).toContain('循環素材の事業仮説');
    expect(view.querySelector('[data-founder-graph-detail]').textContent).toContain('idea');
    expect(view.querySelector('[data-founder-graph-detail]').textContent).toContain('製造現場の廃材を再利用する仮説');
    expect(view.querySelector('[data-founder-graph-detail]').textContent).toContain('active');
    expect(view.querySelector('[data-founder-graph-detail]').textContent).toContain('person-1 → can_contribute_to → idea-1');
    expect(view.textContent).not.toContain('private@example.test');
    expect(view.textContent).not.toContain('do not render this');
    expect(view.textContent).not.toContain('raw source text');
    expect(view.textContent).not.toContain('raw content');
    expect(view.textContent).not.toContain('local-only raw content');
  });

  it.each([
    ['loading', 'Founder Graphを読み込んでいます。', 'status'],
    ['unavailable', 'Founder Graphは現在利用できません。', 'status'],
    ['error', 'Founder Graphの読み込みに失敗しました。', 'alert'],
  ])('announces the %s state without stale result data', (state, message, role) => {
    const view = renderSurface({ state });

    expect(view.querySelector(`[role="${role}"]`).textContent).toContain(message);
    expect(view.querySelectorAll('[data-founder-graph-card]')).toHaveLength(0);
    expect(view.querySelector('[data-founder-graph-detail]')).toBeNull();
  });

  it('announces an empty category distinctly when the graph is ready', () => {
    const view = renderSurface({ results: [] });

    expect(view.querySelector('[role="status"]').textContent).toContain('このカテゴリにはノードがありません。');
    expect(view.querySelectorAll('[data-founder-graph-card]')).toHaveLength(0);
  });

  it('keeps the default surface at four categories when no report versions are supplied', () => {
    const view = renderSurface({ reports: {} });

    expect(view.querySelectorAll('[data-founder-graph-category-tab]')).toHaveLength(4);
    expect(view.querySelector('[data-founder-graph-report-diff]')).toBeNull();
  });

  it('adds an optional Reports category and mounts the read-only report diff', () => {
    const view = renderSurface({
      reports: {
        previousReport,
        currentReport,
      },
    });
    const categoryTabs = [...view.querySelectorAll('[data-founder-graph-category-tab]')];

    expect(categoryTabs.map((tab) => tab.textContent)).toEqual(['Ideas', 'Assets', 'Sources', 'People', 'Reports']);
    expect(categoryTabs[4].getAttribute('aria-selected')).toBe('false');

    act(() => categoryTabs[4].click());

    expect(categoryTabs[4].getAttribute('aria-selected')).toBe('true');
    expect(view.querySelector('[data-founder-graph-report-diff]')).toBeTruthy();
    expect(view.textContent).toContain('現版の要約');
    expect(view.querySelector('[data-founder-graph-report-diff] [role="tablist"]')).toBeTruthy();
  });

  it('keeps report loading failures inside the optional Reports panel', () => {
    const view = renderSurface({
      reports: {
        previousReport,
        currentReport,
        state: 'unavailable',
      },
    });
    const categoryTabs = [...view.querySelectorAll('[data-founder-graph-category-tab]')];

    act(() => categoryTabs[4].dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, cancelable: true })));
    expect(categoryTabs[0].getAttribute('aria-selected')).toBe('true');

    act(() => categoryTabs[4].click());

    expect(view.querySelector('[data-founder-graph-report-state-message="unavailable"]').textContent)
      .toContain('レポート差分は現在利用できません。');
    expect(view.querySelectorAll('[data-founder-graph-report-tab]')).toHaveLength(0);
    expect(view.querySelectorAll('[data-founder-graph-card]')).toHaveLength(0);
  });
});
