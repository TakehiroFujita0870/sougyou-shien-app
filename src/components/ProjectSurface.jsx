import { demoProjectFixture } from './projectDemoFixtureAdapter';
import { Button } from './ui/button';
import { Card } from './ui/card';
import { Textarea } from './ui/textarea';

const sectionLabels = ['事業', '市場', '競合', '利益', '実現性'];

export function ProjectSurface({ state = 'populated', project = demoProjectFixture }) {
  const status = { loading: '読み込み中', error: '確認できません', empty: '確認待ち', populated: project.status }[state];

  return (
    <section aria-labelledby="project-surface-heading" className="max-w-3xl">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.16em] text-stone-500">Project</p>
          <h1 id="project-surface-heading" className="mt-2 text-2xl font-semibold tracking-tight">{project.name}</h1>
          <p className="mt-1 text-sm text-stone-600">管理者デモ · 採用済み案件</p>
        </div>
        <span role="status" className="rounded-full border border-stone-300 px-3 py-1 text-xs font-semibold text-stone-600">{status}</span>
      </div>

      <Card className="mt-5 border-stone-300 p-3" aria-label="Project Kadode AI composer">
        <form>
        <label htmlFor="project-composer" className="text-sm font-semibold">Project Kadode AI</label>
        <Textarea id="project-composer" aria-describedby="project-composer-hint" className="mt-2" placeholder="この案件について聞いてみる" />
        <p id="project-composer-hint" className="mt-2 text-xs text-stone-500">Enterで送信 · Shift+Enterで改行</p>
        <div className="mt-2 flex justify-end"><Button type="button">送信</Button></div>
        </form>
      </Card>

      <div className="mt-5 grid gap-2" aria-label="事業評価の観点">
        {sectionLabels.map((label) => {
          const item = project.sections[label];
          return <Card as="article" key={label} className="px-4 py-3">
            <div className="flex flex-wrap items-baseline justify-between gap-2"><h2 className="text-sm font-bold">{label}</h2><span className="text-xs font-semibold text-stone-500">{item.status}</span></div>
            <p className="mt-1 text-sm text-stone-700">{state === 'loading' ? '読み込み中です。' : state === 'error' ? '現在確認できません。' : item.summary}</p>
            <p className="mt-2 text-xs text-stone-500"><span className="font-semibold text-stone-600">根拠:</span> {item.evidence} · <span className="font-semibold text-stone-600">未確定:</span> {item.unknown}</p>
          </Card>;
        })}
      </div>
    </section>
  );
}
