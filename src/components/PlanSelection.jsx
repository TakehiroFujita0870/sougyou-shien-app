import { useState } from 'react';

const PLAN_DETAILS = {
  free: {
    name: 'Free',
    summary: '軽量モデルで、まず一案を育てるプランです。',
    benefits: ['軽量モデル', 'Thinkingなし', '手動調査に上限あり'],
  },
  standard: {
    name: 'Standard',
    summary: '複数のモデルを選べる、比較と検証を進めるプランです。',
    benefits: ['月額980円', '複数モデル', '既定 GPT-5.6 Terra', 'Freeより大きい調査枠'],
  },
};

export function PlanSelection({ currentPlan, onApplyPlan }) {
  const [proposedPlan, setProposedPlan] = useState(currentPlan);
  const [isConfirming, setIsConfirming] = useState(false);
  const isChangePending = proposedPlan !== currentPlan;
  const detail = PLAN_DETAILS[proposedPlan];

  function choosePlan(plan) {
    setProposedPlan(plan);
    setIsConfirming(plan !== currentPlan);
  }

  function applyChange() {
    onApplyPlan?.(proposedPlan);
    setIsConfirming(false);
  }

  function cancelChange() {
    setProposedPlan(currentPlan);
    setIsConfirming(false);
  }

  return (
    <section aria-labelledby="plan-selection-heading" className="rounded-3xl border border-stone-200 bg-white p-6 shadow-sm">
      <div>
        <p className="text-sm font-bold text-emerald-700">local / fake 契約</p>
        <h1 id="plan-selection-heading" className="mt-2 text-2xl font-bold">プランを確認する</h1>
        <p className="mt-2 text-sm leading-6 text-stone-600">現在のプラン: <strong>{PLAN_DETAILS[currentPlan].name}</strong></p>
        <p className="mt-2 rounded-xl bg-amber-50 px-3 py-2 text-sm leading-6 text-amber-950">外部課金には接続していません。変更はこの画面内の確認用です。</p>
      </div>

      <fieldset className="mt-6 grid gap-4 sm:grid-cols-2">
        <legend className="text-sm font-bold text-stone-800">選択するプラン</legend>
        {Object.entries(PLAN_DETAILS).map(([plan, planDetail]) => (
          <label key={plan} className={`block cursor-pointer rounded-2xl border p-4 focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-emerald-800 ${proposedPlan === plan ? 'border-emerald-700 bg-emerald-50' : 'border-stone-200'}`}>
            <span className="flex items-center gap-3"><input type="radio" name="plan" value={plan} checked={proposedPlan === plan} onChange={() => choosePlan(plan)} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') choosePlan(plan); }} className="size-5 accent-emerald-800" /><strong>{planDetail.name}</strong></span>
            <span className="mt-3 block text-sm leading-6 text-stone-700">{planDetail.summary}</span>
            <ul className="mt-3 space-y-1 text-sm text-stone-700">{planDetail.benefits.map((benefit) => <li key={benefit}>{benefit}</li>)}</ul>
          </label>
        ))}
      </fieldset>

      {isConfirming && isChangePending && (
        <section aria-live="polite" aria-labelledby="plan-confirmation-heading" className="mt-6 rounded-2xl border border-emerald-200 bg-emerald-50 p-4">
          <h2 id="plan-confirmation-heading" className="font-bold">変更内容を確認</h2>
          <p className="mt-1 text-sm leading-6">{detail.name}へ変更します。申込確定や外部決済は行いません。</p>
          <div className="mt-4 flex flex-wrap gap-3"><button type="button" onClick={applyChange} className="min-h-11 rounded-full bg-emerald-800 px-5 py-2 text-sm font-bold text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-800">変更を適用</button><button type="button" onClick={cancelChange} className="min-h-11 rounded-full border border-emerald-800 px-5 py-2 text-sm font-bold text-emerald-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-800">キャンセル</button></div>
        </section>
      )}
    </section>
  );
}
