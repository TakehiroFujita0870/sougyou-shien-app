// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it } from 'vitest';
import { ProjectSurface, projectEvaluationTabs } from './ProjectSurface';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let root;
let container;

afterEach(() => {
  if (root) act(() => root.unmount());
  container?.remove();
  root = undefined;
  container = undefined;
});

const project = {
  datasetId: 'project-tabs-test',
  name: '地域の小さな学び場',
  status: '検討中',
  overview: '親子が学びを続けられる場を考えます。',
  decisions: [],
  sections: Object.fromEntries(projectEvaluationTabs.map((label, index) => [label, {
    status: index === 1 ? '確認中' : '未確認',
    summary: `${label}の要点`,
    evidence: `${label}の根拠`,
    unknown: `${label}の未確認`,
  }])),
};

describe('ProjectSurface evaluation tabs', () => {
  it('uses one accessible active panel and changes it with ArrowRight', async () => {
    container = document.createElement('div');
    document.body.append(container);
    root = createRoot(container);
    await act(async () => { root.render(<ProjectSurface project={project} conversationRepository={{ load: async () => [], save: async (messages) => messages }} />); });
    const tabs = [...container.querySelectorAll('[role="tab"]')];
    expect(tabs.map((tab) => tab.textContent)).toEqual(projectEvaluationTabs);
    expect(tabs).toHaveLength(5);
    expect(tabs[0].getAttribute('aria-selected')).toBe('true');
    expect(container.querySelectorAll('[role="tabpanel"]')).toHaveLength(1);
    expect(container.textContent).toContain('どんな事業？の根拠');
    await act(async () => { tabs[0].dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, cancelable: true })); });
    expect(tabs[1].getAttribute('aria-selected')).toBe('true');
    expect(container.textContent).toContain('市場はある？の根拠');
    expect(container.textContent).toContain('市場はある？の未確認');
  });

  it('shows onboarding instead of a fixed demo business when no project is available', async () => {
    container = document.createElement('div');
    document.body.append(container);
    root = createRoot(container);
    await act(async () => { root.render(<ProjectSurface conversationRepository={{ load: async () => [], save: async (messages) => messages }} />); });
    expect(container.textContent).toContain('Projectをはじめる');
    expect(container.querySelector('#project-composer')).toBeNull();
    expect(container.textContent).toContain('一時的な下書きを試す');
    expect(container.textContent).toContain('この下書きはまだ保存されません。');
    expect(container.textContent).not.toContain('現場改善');
  });

  it('renders persisted legacy profit evidence under the modern display label', async () => {
    const legacyProject = {
      ...project,
      sections: {
        ...project.sections,
        '利益はでる？': {
          status: '計算済み',
          summary: '既存の利益仮説を表示する',
          evidence: '既存の利益根拠を表示する',
          unknown: '既存の利益未確認を表示する',
        },
      },
    };
    delete legacyProject.sections['利益は出る？'];

    container = document.createElement('div');
    document.body.append(container);
    root = createRoot(container);
    await act(async () => { root.render(<ProjectSurface project={legacyProject} conversationRepository={{ load: async () => [], save: async (messages) => messages }} />); });
    const profitTab = [...container.querySelectorAll('[role="tab"]')].find((tab) => tab.textContent === '利益は出る？');

    await act(async () => { profitTab.click(); });

    expect(container.textContent).toContain('既存の利益仮説を表示する');
    expect(container.textContent).toContain('既存の利益根拠を表示する');
    expect(container.textContent).toContain('既存の利益未確認を表示する');
  });

  it('does not expose a misleading Project-only context notice', async () => {
    container = document.createElement('div');
    document.body.append(container);
    root = createRoot(container);
    await act(async () => { root.render(<ProjectSurface project={project} conversationRepository={{ load: async () => [], save: async (messages) => messages }} />); });

    expect(container.textContent).not.toContain('このProjectの文脈だけを使います');
  });
});
