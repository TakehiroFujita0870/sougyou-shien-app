import { MODEL_CATALOG } from '../models/modelCatalog';

export const HOME_MODEL_STORAGE_KEY = 'kadode:home-model';
export const DEFAULT_HOME_MODEL_KEY = MODEL_CATALOG.find((model) => model.logicalKey === 'gpt-5.6-terra')?.logicalKey ?? MODEL_CATALOG[0].logicalKey;

export function getHomeModels() { return MODEL_CATALOG.filter((model) => model.enabled); }

export function createHomeModelRepository(storage = globalThis.localStorage) {
  let modelKey = DEFAULT_HOME_MODEL_KEY;
  return {
    get: () => modelKey,
    load: async () => {
      try {
        const stored = storage?.getItem(HOME_MODEL_STORAGE_KEY);
        if (getHomeModels().some((model) => model.logicalKey === stored)) modelKey = stored;
      } catch { /* retain the catalog default */ }
      return modelKey;
    },
    save: async (next) => {
      if (!getHomeModels().some((model) => model.logicalKey === next)) return modelKey;
      storage?.setItem(HOME_MODEL_STORAGE_KEY, next); modelKey = next; return modelKey;
    },
  };
}
