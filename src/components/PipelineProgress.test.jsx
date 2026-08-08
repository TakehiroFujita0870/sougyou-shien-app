import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { getStageState, PipelineProgress } from './PipelineProgress';

describe('PipelineProgress', () => {
  it('classifies completed, current and upcoming stages', () => {
    expect(getStageState(0, 2)).toBe('completed');
    expect(getStageState(2, 2)).toBe('current');
    expect(getStageState(4, 2)).toBe('upcoming');
  });

  it('marks the current stage for assistive technology', () => {
    const html = renderToStaticMarkup(<PipelineProgress currentStage={1} />);
    expect(html).toContain('aria-current="step"');
    expect(html).toContain('反証');
    expect(html).toContain('現在地');
  });
});
