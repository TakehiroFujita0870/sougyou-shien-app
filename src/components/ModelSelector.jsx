import { getDefaultModel, getModelsForPlan, getReasoningModes } from '../models/modelEntitlements';

const PLAN_LABELS = {
  free: 'Free',
  standard: 'Standard',
};

const REASONING_LABELS = {
  low: 'Low',
  medium: 'Medium',
  high: 'High',
};

export function ModelSelector({ plan, selectedModelKey, selectedReasoningMode, onModelChange, onReasoningModeChange }) {
  const models = getModelsForPlan(plan);
  const defaultModel = getDefaultModel(plan);
  const activeModelKey = models.some((model) => model.logicalKey === selectedModelKey)
    ? selectedModelKey
    : defaultModel?.logicalKey ?? '';
  const reasoningModes = getReasoningModes(plan, activeModelKey);

  return (
    <section aria-labelledby="model-selector-heading" className="rounded-3xl border border-stone-200 bg-white p-6 shadow-sm">
      <div>
        <p className="text-sm font-bold text-emerald-700">利用プラン: {PLAN_LABELS[plan] ?? '未選択'}</p>
        <h2 id="model-selector-heading" className="mt-2 text-xl font-bold">AIモデルを選ぶ</h2>
        <p className="mt-1 text-sm leading-6 text-stone-600">この画面は選択内容の確認用です。外部のAIサービスには送信しません。</p>
      </div>

      <label htmlFor="model" className="mt-6 block text-sm font-bold text-stone-800">モデル</label>
      <select
        id="model"
        value={activeModelKey}
        onChange={(event) => onModelChange?.(event.target.value)}
        disabled={models.length === 0}
        className="mt-2 w-full rounded-xl border border-stone-300 bg-white px-4 py-3 focus:border-emerald-700 focus:ring-2 focus:ring-emerald-100 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {models.map((model) => <option key={model.logicalKey} value={model.logicalKey}>{model.displayName}</option>)}
      </select>

      {reasoningModes.length > 0 && (
        <>
          <label htmlFor="reasoning-effort" className="mt-5 block text-sm font-bold text-stone-800">Thinking Effort</label>
          <select
            id="reasoning-effort"
            value={reasoningModes.includes(selectedReasoningMode) ? selectedReasoningMode : reasoningModes[0]}
            onChange={(event) => onReasoningModeChange?.(event.target.value)}
            className="mt-2 w-full rounded-xl border border-stone-300 bg-white px-4 py-3 focus:border-emerald-700 focus:ring-2 focus:ring-emerald-100"
          >
            {reasoningModes.map((mode) => <option key={mode} value={mode}>{REASONING_LABELS[mode]}</option>)}
          </select>
        </>
      )}
    </section>
  );
}
