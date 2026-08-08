import { MODEL_CATALOG, PLAN } from './modelCatalog';

function isKnownPlan(plan) {
  return Object.values(PLAN).includes(plan);
}

export function getModelsForPlan(plan) {
  if (!isKnownPlan(plan)) return [];

  return MODEL_CATALOG.filter((model) => model.enabled && model.plans.includes(plan));
}

export function isModelAllowedForPlan(plan, logicalKey) {
  return getModelsForPlan(plan).some((model) => model.logicalKey === logicalKey);
}

export function getDefaultModel(plan) {
  const models = getModelsForPlan(plan);
  return models.find((model) => model.isDefault) ?? models[0] ?? null;
}

export function getReasoningModes(plan, logicalKey) {
  if (plan === PLAN.FREE || !isModelAllowedForPlan(plan, logicalKey)) return [];

  return getModelsForPlan(plan).find((model) => model.logicalKey === logicalKey)?.reasoningModes ?? [];
}
