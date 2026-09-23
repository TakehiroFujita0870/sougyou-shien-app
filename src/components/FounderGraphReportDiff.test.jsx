// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it } from 'vitest';
import {
  FOUNDER_GRAPH_REPORT_CHAPTERS,
  FounderGraphReportDiff,
} from './FounderGraphReportDiff';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const previousReport = {
  id: 'report-previous',
  status: 'draft',
  created_at: '2026-09-20T00:00:00Z',
  references: [{ id: 'source-old', label: '旧調査資料' }],
  withdrawn_claims: [{ id: 'claim-old', label: '撤回前の市場仮説', reason: '反証された' }],
  sections: [
    { id: 0, content: '同じ要約' },
    { id: 1, content: '旧ビジネスモデル' },
    null,
    { id: 3, content: '同じ収益モデル' },
    { id: 4, content: '同じ競争優位性' },
    { id: 5, content: '同じ実現可能性' },
    { id: 6, content: '同じリスク' },
    { id: 7, content: '同じロードマップ' },
  ],
};

const currentReport = {
  id: 'report-current',
  status: 'final',
  created_at: '2026-09-21T00:00:00Z',
  references: [{ id: 'source-new', label: '新しい市場調査' }],
  withdrawn_claims: [{ id: 'claim-old', label: '撤回前の市場仮説', reason: '反証された' }],
  sections: [
    { id: 0, content: '同じ要約' },
    { id: 1, content: '新ビジネスモデル', references: ['source-model'] },
    { id: 2, content: '新しい顧客仮説', withdrawn_claims: ['claim-withdrawn'] },
    { id: 3, content: '同じ収益モデル' },
    { id: 4, content: '同じ競争優位性' },
    { id: 5, content: '同じ実現可能性' },
    { id: 6, content: '同じリスク' },
    { id: 7, content: '同じロードマップ' },
  ],
};

let root;
let container;

afterEach(() => {
  if (root) act(() => root.unmount());
  container?.remove();
  root = undefined;
  container = undefined;
});

function renderDiff(props = {}) {
  container = document.createElement('div');
  document.body.append(container);
  root = createRoot(container);
  act(() => root.render(
    <FounderGraphReportDiff
      previousReport={previousReport}
      currentReport={currentReport}
      {...props}
    />,
  ));
  return container;
}

describe('FounderGraphReportDiff', () => {
  it('renders all eight fixed chapters and classifies added, changed, and unchanged chapters', () => {
    const view = renderDiff();
    const tabs = [...view.querySelectorAll('[data-founder-graph-report-tab]')];

    expect(tabs).toHaveLength(8);
    expect(tabs.map((tab) => tab.textContent)).toEqual([
      '0 エグゼクティブサマリー変更なし',
      '1 ビジネスモデル変更',
      '2 顧客とマーケットサイズ追加',
      '3 収益モデル変更なし',
      '4 競争優位性変更なし',
      '5 実現可能性変更なし',
      '6 リスク・撤退ライン変更なし',
      '7 リスクミニマムなロードマップ変更なし',
    ]);
    expect(view.querySelectorAll('[data-founder-graph-change-status="changed"]')).toHaveLength(1);
    expect(view.querySelectorAll('[data-founder-graph-change-status="added"]')).toHaveLength(1);
    expect(view.querySelectorAll('[data-founder-graph-change-status="unchanged"]')).toHaveLength(6);
    act(() => tabs[1].click());
    expect(view.textContent).toContain('新ビジネスモデル');
  });

  it('switches the chapter panel with ArrowRight and preserves accessible tab semantics', () => {
    const view = renderDiff();
    const tabs = [...view.querySelectorAll('[role="tab"]')];

    expect(view.querySelector('[role="tablist"]').getAttribute('aria-label')).toBe('事業評価レポートの章');
    expect(tabs[0].getAttribute('aria-selected')).toBe('true');
    expect(tabs[0].getAttribute('aria-controls')).toBeTruthy();
    expect(view.querySelector('[role="tabpanel"]').getAttribute('aria-labelledby')).toBe(tabs[0].id);

    act(() => tabs[0].dispatchEvent(new KeyboardEvent('keydown', {
      key: 'ArrowRight',
      bubbles: true,
      cancelable: true,
    })));

    expect(tabs[1].getAttribute('aria-selected')).toBe('true');
    expect(tabs[1].tabIndex).toBe(0);
    expect(view.querySelector('[role="tabpanel"]').textContent).toContain('新ビジネスモデル');
    expect(view.querySelector('[role="tabpanel"]').textContent).toContain('旧ビジネスモデル');
  });

  it('keeps references and withdrawn claims as display-only metadata without rendering private fields', () => {
    const view = renderDiff({
      previousReport: {
        ...previousReport,
        private_notes: '前版の秘密メモ',
        sections: previousReport.sections.map((section) => ({
          ...section,
          source_text: '旧原文を描画しない',
        })),
      },
      currentReport: {
        ...currentReport,
        private_notes: '現版の秘密メモ',
        sections: currentReport.sections.map((section) => ({
          ...section,
          source_text: '現版の原文を描画しない',
        })),
      },
    });

    expect(view.textContent).toContain('新しい市場調査');
    expect(view.textContent).toContain('撤回前の市場仮説');
    act(() => view.querySelectorAll('[data-founder-graph-report-tab]')[2].click());
    expect(view.textContent).toContain('claim-withdrawn');
    expect(view.textContent).toContain('表示のみ');
    expect(view.querySelector('[data-founder-graph-report-metadata]')).toBeTruthy();
    expect(view.textContent).not.toContain('秘密メモ');
    expect(view.textContent).not.toContain('旧原文を描画しない');
    expect(view.textContent).not.toContain('現版の原文を描画しない');
  });

  it('honors an explicit unavailable chapter projection as absent instead of reviving its old content', () => {
    const view = renderDiff({
      currentReport: {
        ...currentReport,
        sections: currentReport.sections.map((section) => (
          section?.id === 1 ? { ...section, present: false } : section
        )),
      },
    });

    const businessModelTab = view.querySelectorAll('[data-founder-graph-report-tab]')[1];
    expect(businessModelTab.textContent).toContain('削除');
    act(() => businessModelTab.click());
    const columns = view.querySelectorAll('[data-founder-graph-report-column]');
    expect(columns[0].textContent).toContain('旧ビジネスモデル');
    expect(columns[1].textContent).toContain('この版にはこの章がありません。');
    expect(columns[1].textContent).not.toContain('新ビジネスモデル');
  });

  it.each([
    ['loading', 'レポート差分を読み込んでいます。', 'status'],
    ['unavailable', 'レポート差分は現在利用できません。', 'status'],
    ['error', 'レポート差分の読み込みに失敗しました。', 'alert'],
    ['empty', '比較するレポートがありません。', 'status'],
  ])('handles the %s state without stale chapter data', (state, message, role) => {
    const view = renderDiff({ state });

    expect(view.querySelector(`[role="${role}"]`).textContent).toContain(message);
    expect(view.querySelectorAll('[data-founder-graph-report-tab]')).toHaveLength(0);
    expect(view.querySelector('[data-founder-graph-report-export]')).toBeNull();
    expect(view.textContent).not.toContain('新ビジネスモデル');
  });

  it('emits a safe export intent without forwarding report payload or private fields', () => {
    const requests = [];
    const view = renderDiff({
      onExportRequest: (intent) => requests.push(intent),
      previousReport: { ...previousReport, private_notes: '秘密メモ', source_text: '原文' },
      currentReport: { ...currentReport, private_notes: '秘密メモ2', source_text: '原文2' },
    });

    act(() => view.querySelector('[data-founder-graph-export-intent="markdown"]').click());

    expect(requests).toEqual([{
      format: 'markdown',
      scope: 'report_versions',
      projection: 'shareable',
      reportIds: ['report-current', 'report-previous'],
    }]);
    expect(JSON.stringify(requests)).not.toContain('秘密メモ');
    expect(JSON.stringify(requests)).not.toContain('原文');
  });

  it('does not emit export intent while export preparation is unavailable', () => {
    const requests = [];
    const view = renderDiff({
      exportState: 'unavailable',
      onExportRequest: (intent) => requests.push(intent),
    });

    expect(view.querySelector('[data-founder-graph-report-export]').getAttribute('data-founder-graph-export-state')).toBe('unavailable');
    expect(view.querySelector('[data-founder-graph-export-state-message="unavailable"]').getAttribute('role')).toBe('alert');
    expect(view.querySelectorAll('[data-founder-graph-export-intent]')).toHaveLength(2);
    expect([...view.querySelectorAll('[data-founder-graph-export-intent]')].every((button) => button.disabled)).toBe(true);

    act(() => view.querySelector('[data-founder-graph-export-intent="json"]').click());
    expect(requests).toEqual([]);
  });

  it('uses the exact fixed chapter names exported by the component contract', () => {
    expect(FOUNDER_GRAPH_REPORT_CHAPTERS.map(({ id, title }) => `${id} ${title}`)).toEqual([
      '0 エグゼクティブサマリー',
      '1 ビジネスモデル',
      '2 顧客とマーケットサイズ',
      '3 収益モデル',
      '4 競争優位性',
      '5 実現可能性',
      '6 リスク・撤退ライン',
      '7 リスクミニマムなロードマップ',
    ]);
  });
});
