import { getDefaultModel, getReasoningModes, isModelAllowedForPlan } from '../models/modelEntitlements';
import { PLAN } from '../models/modelCatalog';

export const DEFAULT_PLAN = PLAN.FREE;
export const PLAN_STORAGE_KEY = 'kadode:plan-selection';

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

export function createLocalPlanRepository(initialSelection = {}, storage = globalThis.localStorage) {
  let subscription = normalizePlanSelection(initialSelection.plan ?? DEFAULT_PLAN, initialSelection);
  let hydrationPromise;

  async function load() {
    if (hydrationPromise) return hydrationPromise;
    hydrationPromise = Promise.resolve().then(() => {
      try {
        const raw = storage?.getItem(PLAN_STORAGE_KEY);
        if (raw) {
          const parsed = JSON.parse(raw);
          subscription = normalizePlanSelection(parsed.plan ?? DEFAULT_PLAN, parsed);
        }
      } catch { /* retain the last known safe subscription */ }
      return subscription;
    });
    return hydrationPromise;
  }

  async function save(selection = subscription) {
    const next = normalizePlanSelection(selection.plan ?? DEFAULT_PLAN, selection);
    try {
      storage?.setItem(PLAN_STORAGE_KEY, JSON.stringify(next));
      subscription = next;
      return { subscription, error: '' };
    } catch {
      return { subscription, error: 'プラン設定を保存できませんでした。' };
    }
  }

  return {
    getSubscription: () => subscription,
    load,
    save,
    applyPlan: (plan, selection = subscription) => {
      const isPlanChange = plan !== subscription.plan;
      subscription = normalizePlanSelection(plan, isPlanChange ? {} : selection);
      return subscription;
    },
  };
}
