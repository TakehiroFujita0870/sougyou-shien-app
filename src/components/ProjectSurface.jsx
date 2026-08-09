import { useState } from 'react';
import { ArrowUp, FileText, Paperclip, Sparkles } from 'lucide-react';
import { demoProjectFixture } from './projectDemoFixtureAdapter';
import { Badge } from './ui/Badge';
import { Button } from './ui/Button';
import { Card } from './ui/Card';

const sectionLabels = ['どんな事業？', '市場はある？', '競合は誰？', '利益はでる？', '実現できる？'];

function Composer({ onSubmit }) {
  const [message, setMessage] = useState('');
  const submit = () => {
    const next = message.trim();
    if (!next) return;
    onSubmit(next);
    setMessage('');
  };

  return (
    <form
      className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-3 shadow-sm"
      aria-label="Project Kadode AI composer"
      onSubmit={(event) => { event.preventDefault(); submit(); }}
    >
      <label htmlFor="project-composer" className="sr-only">このプロジェクトについて Kadode AI に聞く</label>
      <textarea
        id="project-composer"
        className="min-h-24 w-full resize-none bg-transparent px-2 py-1 text-base leading-7 outline-none placeholder:text-[var(--color-text-muted)]"
        value={message}
        onChange={(event) => setMessage(event.target.value)}
        onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); submit(); } }}
        placeholder="このプロジェクトについて、考えたいことを入力…"
      />
      <div className="flex items-center justify-between gap-2 border-t border-[var(--color-border-subtle)] pt-2">
        <div className="flex items-center gap-1">
          <Button type="button" variant="ghost" className="min-h-9 px-2" aria-label="資料を添付（準備中）" title="資料を添付（準備中）"><Paperclip className="size-4" /></Button>
          <Button type="button" variant="ghost" className="min-h-9 gap-1.5 px-2.5 text-xs" aria-label="AIで入力を補完（準備中）"><Sparkles className="size-3.5" />補完</Button>
        </div>
        <Button type="submit" className="min-h-9 rounded-lg px-3" aria-label="送信"><ArrowUp className="size-4" /></Button>
      </div>
    </form>
  );
}

export function ProjectSurface({ state = 'populated', project: projectFixture = demoProjectFixture, adoptedProject }) {
  const [messages, setMessages] = useState([]);
  const [exported, setExported] = useState(false);
  const [decisionFilter, setDecisionFilter] = useState('all');
  const resolvedProject = adoptedProject
    ? {
      name: adoptedProject.title,
      status: adoptedProject.status,
      overview: adoptedProject.inference,
      decisions: adoptedProject.reason ? [{ id: `${adoptedProject.id}-adoption`, kind: 'adopted', date: '', title: adoptedProject.title, reason: adoptedProject.reason }] : [],
      sections: Object.fromEntries(sectionLabels.map((label) => [label, { status: '未確認', summary: 'この仮説をProjectで検討します。', evidence: adoptedProject.fact, unknown: 'Projectでの会話から具体化します。' }])),
    }
    : projectFixture;
  const project = resolvedProject;
  const status = { loading: '読み込み中', error: '確認が必要です', empty: '準備中', populated: project.status }[state];
  const decisions = resolvedProject.decisions?.filter((decision) => decisionFilter === 'all' || decision.kind === decisionFilter) ?? [];

  return (
    <section aria-labelledby="project-surface-heading" className="mx-auto w-full max-w-6xl pb-12">
      <header className="flex flex-wrap items-start justify-between gap-4 border-b border-[var(--color-border-subtle)] pb-6">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.16em] text-[var(--color-text-muted)]">PROJECT</p>
          <div className="mt-2 flex flex-wrap items-center gap-3"><h1 id="project-surface-heading" className="text-3xl font-semibold tracking-tight">{project.name}</h1><Badge variant="outline">{status}</Badge></div>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-[var(--color-text-muted)]">{project.overview}</p>
          {adoptedProject && <div className="mt-3 space-y-1 text-sm"><p><strong>事実:</strong> {adoptedProject.fact}</p><p><strong>推論:</strong> {adoptedProject.inference}</p><p><strong>採用理由:</strong> {adoptedProject.reason}</p></div>}
        </div>
        <Button type="button" variant="secondary" className="gap-2" onClick={() => setExported(true)}><FileText className="size-4" />事業計画書をエクスポート</Button>
      </header>
      {exported && <p className="mt-3 text-sm text-[var(--color-text-muted)]" role="status">事業計画書の下書きを用意しました。内容を確認してから書き出せます。</p>}

      <div className="mt-7 grid gap-8 lg:grid-cols-[minmax(0,1.3fr)_minmax(19rem,.7fr)]">
        <div className="min-w-0 space-y-7">
          <div>
            <div className="mb-3 flex items-center justify-between gap-3"><h2 className="text-base font-semibold">Kadode AI と検討する</h2><span className="text-xs text-[var(--color-text-muted)]">このプロジェクトの情報を参照します</span></div>
            {messages.length > 0 && <ol className="mb-4 space-y-3" aria-label="会話履歴">{messages.map((message, index) => <li key={`${message}-${index}`} className="ml-auto max-w-[85%] rounded-2xl bg-[var(--color-muted)] px-4 py-3 text-sm leading-6">{message}</li>)}</ol>}
            <Composer onSubmit={(message) => setMessages((current) => [...current, message])} />
          </div>

          <div aria-labelledby="project-questions-heading">
            <div className="mb-3 flex items-baseline justify-between gap-3"><h2 id="project-questions-heading" className="text-base font-semibold">事業を具体化する</h2><p className="text-xs text-[var(--color-text-muted)]">根拠と未確認を分けて記録</p></div>
            <div className="grid gap-3 md:grid-cols-2">{sectionLabels.map((label) => {
              const item = resolvedProject.sections[label];
              return <Card key={label} data-project-question="true" className="p-4"><div className="flex items-baseline justify-between gap-3"><h3 className="font-semibold">{label}</h3><Badge variant="secondary">{item.status}</Badge></div><p className="mt-3 text-sm leading-6">{state === 'loading' ? '読み込み中です。' : state === 'error' ? '確認が必要です。' : item.summary}</p><dl className="mt-4 space-y-2 border-t border-[var(--color-border-subtle)] pt-3 text-xs leading-5"><div><dt className="font-semibold text-[var(--color-text-muted)]">根拠</dt><dd>{item.evidence}</dd></div><div><dt className="font-semibold text-[var(--color-text-muted)]">未確認</dt><dd>{item.unknown}</dd></div></dl></Card>;
            })}</div>
          </div>
        </div>

        <aside className="space-y-4" aria-labelledby="decision-history-heading">
          <div className="flex items-center justify-between gap-2"><h2 id="decision-history-heading" className="text-base font-semibold">採用・保留・却下</h2><select aria-label="履歴を絞り込む" value={decisionFilter} onChange={(event) => setDecisionFilter(event.target.value)} className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-raised)] px-2 py-1 text-xs"><option value="all">すべて</option><option value="採用">採用</option><option value="保留">保留</option><option value="却下">却下</option></select></div>
          <Card className="divide-y divide-[var(--color-border-subtle)]">{decisions.length ? decisions.map((decision) => <div key={decision.id} className="p-4"><div className="flex items-center justify-between gap-2"><Badge variant={decision.kind === '採用' ? 'default' : 'outline'}>{decision.kind}</Badge><time className="text-xs text-[var(--color-text-muted)]">{decision.date}</time></div><p className="mt-3 text-sm font-medium">{decision.title}</p><p className="mt-1 text-xs leading-5 text-[var(--color-text-muted)]">{decision.reason}</p></div>) : <p className="p-4 text-sm text-[var(--color-text-muted)]">この条件の履歴はありません。</p>}</Card>
        </aside>
      </div>
    </section>
  );
}
