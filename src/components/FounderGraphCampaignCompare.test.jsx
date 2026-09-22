// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it } from 'vitest';
import { FounderGraphCampaignCompare, projectFounderGraphCampaignCompare } from './FounderGraphCampaignCompare';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const campaign = { id: 'campaign-1', purpose: '名刺管理の先の事業性検証', status: 'approved', trial_budget: 2, private_notes: '秘密' };
const runs = [
  { id: 'run-1', status: 'completed', model_snapshot: 'luna@v1', input_snapshot: { secret: 'x' } },
  { id: 'run-2', status: 'partial', model_snapshot: 'luna@v1' },
];
const previousReport = { id: 'report-1', status: 'draft', sections: [{ id: 0, content: '前版' }] };
const currentReport = { id: 'report-2', status: 'final', sections: [{ id: 0, content: '現版' }] };

let root;
let container;

afterEach(() => {
  if (root) act(() => root.unmount());
  container?.remove();
  root = undefined;
  container = undefined;
});

function renderCompare(props = {}) {
  container = document.createElement('div');
  document.body.append(container);
  root = createRoot(container);
  act(() => root.render(<FounderGraphCampaignCompare campaign={campaign} runs={runs} previousReport={previousReport} currentReport={currentReport} {...props} />));
  return container;
}

describe('FounderGraphCampaignCompare', () => {
  it('projects only safe campaign/run metadata and composes the fixed report diff', () => {
    const view = renderCompare();
    expect(view.querySelector('[data-founder-graph-campaign-metadata]')).toBeTruthy();
    expect(view.textContent).toContain('campaign-1');
    expect(view.textContent).toContain('run-1');
    expect(view.textContent).toContain('run-2');
    expect(view.querySelectorAll('[data-founder-graph-report-tab]')).toHaveLength(8);
    expect(view.textContent).not.toContain('秘密');
    expect(view.textContent).not.toContain('secret');
  });

  it('deduplicates runs and drops unknown/private fields in the projection', () => {
    const projection = projectFounderGraphCampaignCompare({
      campaign: { ...campaign, unknown: 'drop' },
      runs: [{ ...runs[0] }, { ...runs[0], status: 'duplicate' }, { private_notes: 'drop' }],
      previousReport,
      currentReport,
    });
    expect(projection.campaign).toEqual({ id: 'campaign-1', purpose: campaign.purpose, status: 'approved', trial_budget: '2' });
    expect(projection.runs).toEqual([{ id: 'run-1', status: 'completed', model_snapshot: 'luna@v1' }]);
  });

  it.each(['loading', 'unavailable', 'error', 'empty'])('renders %s without report tabs', (state) => {
    const view = renderCompare({ state });
    expect(view.querySelector(`[data-founder-graph-campaign-state-message="${state}"]`)).toBeTruthy();
    expect(view.querySelectorAll('[data-founder-graph-report-tab]')).toHaveLength(0);
  });

  it('renders an empty state when campaign or runs are absent', () => {
    const view = renderCompare({ campaign: null, runs: [] });
    expect(view.querySelector('[data-founder-graph-campaign-state-message="empty"]')).toBeTruthy();
    expect(view.textContent).not.toContain('前版');
  });
});
