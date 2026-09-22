// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it } from 'vitest';

import { App } from './App';
import { EMPTY_PROFILE } from './components/UserProfileInterview';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const profileRepository = {
  load: async () => ({ values: EMPTY_PROFILE, step: 5, status: 'completed', error: '' }),
  save: async (profile) => profile,
};

const reports = {
  previousReport: { id: 'report-previous', sections: [] },
  currentReport: { id: 'report-current', sections: [] },
};

async function mount(props = {}) {
  sessionStorage.setItem('dots:selected-surface', 'home');
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(<App profileRepository={profileRepository} {...props} />);
  });
  await act(async () => Promise.resolve());
  return {
    container,
    openGraph: async () => {
      const graphButton = [...container.querySelectorAll('.workspace-shell__nav-item')]
        .find((button) => button.textContent === 'Graph');
      await act(async () => graphButton.click());
    },
    unmount: () => act(() => {
      root.unmount();
      container.remove();
    }),
  };
}

afterEach(() => {
  document.body.replaceChildren();
  sessionStorage.clear();
});

describe('App Founder Graph composition', () => {
  it('passes optional report versions into the Graph surface', async () => {
    const view = await mount({ founderGraphReports: reports });

    await view.openGraph();

    const categoryTabs = [...view.container.querySelectorAll('[data-founder-graph-category-tab]')];
    expect(categoryTabs.map((tab) => tab.textContent)).toEqual(['Ideas', 'Assets', 'Sources', 'People', 'Reports']);
    expect(view.container.querySelector('[data-founder-graph-report-diff]')).toBeNull();

    await act(async () => categoryTabs.at(-1).click());
    expect(view.container.querySelector('[data-founder-graph-report-diff]')).not.toBeNull();

    await view.unmount();
  });

  it('keeps the Graph surface at its empty four-category default without reports', async () => {
    const view = await mount();

    await view.openGraph();

    expect(view.container.querySelectorAll('[data-founder-graph-category-tab]')).toHaveLength(4);
    expect(view.container.querySelector('[data-founder-graph-report-diff]')).toBeNull();

    await view.unmount();
  });
});
