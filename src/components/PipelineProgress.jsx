export const PIPELINE_STAGES = [
  { id: 0, name: '発散', description: 'アイデアとペインを言語化' },
  { id: 1, name: '反証', description: '別の視点で死因を3件検証' },
  { id: 2, name: '深掘り', description: '市場・競合・数字を分析' },
  { id: 3, name: '一次検証', description: '顧客に確かめる計画を作成' },
  { id: 4, name: '決裁', description: '理由と結果を記録' },
];

export function getStageState(stageId, currentStage) {
  if (currentStage === null) return 'upcoming';
  if (stageId < currentStage) return 'completed';
  if (stageId === currentStage) return 'current';
  return 'upcoming';
}

export function PipelineProgress({ currentStage = null }) {
  return (
    <section className="rounded-3xl border border-stone-200 bg-white p-6 shadow-sm" aria-labelledby="pipeline-heading">
      <p className="text-xs font-bold tracking-[0.16em] text-emerald-700">STAGE GATE</p>
      <h2 id="pipeline-heading" className="mt-2 text-2xl font-bold">パイプライン進捗</h2>
      <p className="mt-2 text-sm leading-6 text-stone-600">
        各段階の成果物と条件を満たすまで、次へ進みません。
      </p>

      <ol className="mt-6 grid gap-3">
        {PIPELINE_STAGES.map((stage) => {
          const state = getStageState(stage.id, currentStage);
          const isCurrent = state === 'current';
          return (
            <li
              key={stage.id}
              aria-current={isCurrent ? 'step' : undefined}
              className={`grid grid-cols-[2.5rem_1fr_auto] items-center gap-3 rounded-2xl border p-3 ${stageClassName(state)}`}
            >
              <span className="grid size-10 place-items-center rounded-full border border-current text-sm font-bold">
                {state === 'completed' ? '✓' : stage.id}
              </span>
              <span>
                <strong className="block">{stage.name}</strong>
                <span className="mt-0.5 block text-xs leading-5 opacity-75">{stage.description}</span>
              </span>
              <span className="text-xs font-bold">{stateLabel(state)}</span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function stateLabel(state) {
  if (state === 'completed') return '完了';
  if (state === 'current') return '現在地';
  return '未着手';
}

function stageClassName(state) {
  if (state === 'completed') return 'border-emerald-200 bg-emerald-50 text-emerald-900';
  if (state === 'current') return 'border-emerald-700 bg-emerald-100 text-emerald-950';
  return 'border-stone-200 bg-stone-50 text-stone-500';
}
