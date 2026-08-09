import { useState } from 'react';
import { Badge } from './ui/Badge';
import { Button } from './ui/Button';
import { Card } from './ui/Card';

const PLAN_DETAILS = {
  free: {
    name: 'Free',
    summary: 'まず一案を育て、検討の手触りを確かめるプランです。',
    benefits: ['アイデア整理', '小さな調査枠', 'プロジェクトの基本機能'],
  },
  standard: {
    name: 'Standard',
    summary: '比較と検証を深め、事業の形に近づけるプランです。',
    benefits: ['月額980円', '大きな調査枠', '事業検討の拡張機能'],
  },
};

const PRO_PLAN_DETAILS = {
  name: 'Pro',
  price: '月額2,980円',
  summary: '自動深掘りとメールレポートは、利用量・原価データの蓄積後に別仕様で判断します。',
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
    <Card aria-labelledby="plan-selection-heading" className="rounded-3xl p-6">
      <div>
        <h1 id="plan-selection-heading" className="text-2xl font-bold">プランと利用状況</h1>
        <p className="mt-2 text-sm leading-6 text-stone-600">現在のプラン: <strong>{PLAN_DETAILS[currentPlan].name}</strong></p>
      </div>

      <fieldset className="mt-6 grid gap-4 sm:grid-cols-3">
        <legend className="text-sm font-bold text-stone-800">選択するプラン</legend>
        {Object.entries(PLAN_DETAILS).map(([plan, planDetail]) => (
          <label key={plan} className={`block cursor-pointer rounded-2xl border p-4 focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-emerald-800 ${proposedPlan === plan ? 'border-emerald-700 bg-emerald-50' : 'border-stone-200'}`}>
            <span className="flex items-center gap-3"><input type="radio" name="plan" value={plan} checked={proposedPlan === plan} onChange={() => choosePlan(plan)} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') choosePlan(plan); }} className="size-5 accent-emerald-800" /><strong>{planDetail.name}</strong></span>
            <span className="mt-3 block text-sm leading-6 text-stone-700">{planDetail.summary}</span>
            <ul className="mt-3 space-y-1 text-sm text-stone-700">{planDetail.benefits.map((benefit) => <li key={benefit}>{benefit}</li>)}</ul>
          </label>
        ))}
        <aside aria-labelledby="pro-plan-heading" aria-describedby="pro-plan-availability" className="relative overflow-hidden rounded-2xl border border-stone-200 bg-stone-50 p-4">
          <Badge className="absolute right-3 top-3 bg-[var(--color-text)] text-[var(--color-surface)]">準備中</Badge>
          <p id="pro-plan-heading" className="text-sm font-bold text-stone-800">{PRO_PLAN_DETAILS.name}</p>
          <p className="mt-2 text-lg font-bold text-stone-950">{PRO_PLAN_DETAILS.price}</p>
          <p className="mt-3 text-sm leading-6 text-stone-700">{PRO_PLAN_DETAILS.summary}</p>
          <p id="pro-plan-availability" className="mt-2 text-sm font-bold text-stone-800">提供開始に向けて準備中です。</p>
          <Button type="button" disabled aria-describedby="pro-plan-availability" variant="secondary" className="mt-4 rounded-full">準備中・現在利用不可</Button>
        </aside>
      </fieldset>

      {isConfirming && isChangePending && (
        <section aria-live="polite" aria-labelledby="plan-confirmation-heading" className="mt-6 rounded-2xl border border-emerald-200 bg-emerald-50 p-4">
          <h2 id="plan-confirmation-heading" className="font-bold">変更内容を確認</h2>
          <p className="mt-1 text-sm leading-6">{detail.name}へ利用プランを更新します。</p>
          <div className="mt-4 flex flex-wrap gap-3"><Button type="button" onClick={applyChange} className="rounded-full">変更を適用</Button><Button type="button" onClick={cancelChange} variant="secondary" className="rounded-full">キャンセル</Button></div>
        </section>
      )}
    </Card>
  );
}
