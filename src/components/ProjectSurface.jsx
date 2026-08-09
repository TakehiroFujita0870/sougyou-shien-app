const sections = ['どんな事業', '市場', '競合', '利益', '実現性'];

export const projectFixture = {
  name: '工場ノート',
  status: '検討中',
  sections: Object.fromEntries(sections.map((name) => [name, 'まだ確認していません。'])),
};

export function ProjectSurface({ state = 'empty', project = projectFixture }) {
  const loading = state === 'loading';
  const error = state === 'error';
  return <section aria-labelledby="project-surface-heading" className="max-w-3xl">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><p className="text-xs font-bold uppercase tracking-[0.16em] text-stone-500">Project</p><h1 id="project-surface-heading" className="mt-2 text-2xl font-semibold tracking-tight">{project.name}</h1></div>
      <span className="rounded-full border border-stone-300 px-3 py-1 text-xs font-semibold text-stone-600">{loading ? '読み込み中' : error ? '確認できません' : project.status}</span>
    </div>
    <form className="mt-5 rounded-2xl border border-stone-300 bg-white p-3"><label htmlFor="project-composer" className="sr-only">Projectへのメッセージ</label><textarea id="project-composer" aria-describedby="project-composer-hint" className="min-h-20 w-full resize-y p-2 text-base leading-6 outline-none" placeholder="この事業について話してみる" /><p id="project-composer-hint" className="mt-2 text-xs text-stone-500">Enterで送信、Shift+Enterで改行</p><div className="mt-2 flex justify-end"><button type="button" className="min-h-11 rounded-full bg-stone-900 px-5 py-2 text-sm font-bold text-white">送信</button></div></form>
    <div className="mt-5 grid gap-2" aria-label="事業検討の観点">{sections.map((name) => <article key={name} className="rounded-2xl border border-stone-200 bg-white px-4 py-3"><h2 className="text-sm font-bold">{name}</h2><p className="mt-1 text-sm text-stone-600">{loading ? '読み込み中です。' : error ? '現在確認できません。' : project.sections[name]}</p></article>)}</div>
  </section>;
}
