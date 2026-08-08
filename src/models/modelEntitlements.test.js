import { describe, expect, it } from 'vitest';

import {
  getDefaultModel,
  getModelsForPlan,
  getReasoningModes,
  isModelAllowedForPlan,
} from './modelEntitlements';

describe('model entitlements', () => {
  it('limits Free to a lightweight model without Thinking Effort', () => {
    const [model] = getModelsForPlan('free');

    expect(getModelsForPlan('free')).toHaveLength(1);
    expect(model.costClass).toBe('lightweight');
    expect(getReasoningModes('free', model.logicalKey)).toEqual([]);
  });

  it('uses gpt-5.6-terra as the Standard default and rejects Free-only access to it', () => {
    expect(getDefaultModel('standard').logicalKey).toBe('gpt-5.6-terra');
    expect(isModelAllowedForPlan('standard', 'gpt-5.6-terra')).toBe(true);
    expect(isModelAllowedForPlan('free', 'gpt-5.6-terra')).toBe(false);
  });

  it('never exposes reasoning modes for Free, including an invalid model key', () => {
    expect(getReasoningModes('free', 'not-a-model')).toEqual([]);
  });
});
