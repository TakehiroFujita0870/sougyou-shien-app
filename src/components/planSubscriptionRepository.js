import { getDefaultModel, getReasoningModes, isModelAllowedForPlan } from '../models/modelEntitlements';
import { PLAN } from '../models/modelCatalog';

export const DEFAULT_PLAN = PLAN.FREE;

export function normalizePlanSelection(plan, selection = {}) {
  const defaultModel = getDefaultModel(plan);
  const modelKey = isModelAllowedForPlan(plan, selection.modelKey)
    ? selection.modelKey
    : defaultModel?.logicalKey ?? '';
  const reasoningModes = getReasoningModes(plan, modelKey);

  return {
    plan,
    modelKey,
    reasoningMode: reasoningModes.includes(selection.reasoningMode) ? selection.reasoningMode : (reasoningModes[0] ?? null),
  };
}

export function createLocalPlanRepository(initialSelection = {}) {
  let subscription = normalizePlanSelection(initialSelection.plan ?? DEFAULT_PLAN, initialSelection);

  return {
    getSubscription: () => subscription,
    applyPlan: (plan, selection = subscription) => {
      const isPlanChange = plan !== subscription.plan;
      subscription = normalizePlanSelection(plan, isPlanChange ? {} : selection);
      return subscription;
    },
  };
}
