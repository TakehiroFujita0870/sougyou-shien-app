import { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowUp, FileText, Paperclip, Sparkles } from 'lucide-react';
import { demoProjectFixture } from './projectDemoFixtureAdapter';
import { createProjectConversationRepository } from './projectConversationRepository';
import { Badge } from './ui/Badge';
import { Button } from './ui/Button';
import { Card } from './ui/Card';

const sectionLabels = ['どんな事業？', '市場はある？', '競合は誰？', '利益はでる？', '実現できる？'];

export function nextProjectAssistantReply(projectName, message) {
  return `「${projectName}」について受け取りました。${message.slice(0, 80)} を、顧客・根拠・次に確かめることの順で整理していきましょう。`;
}

function Composer({ disabled, onSubmit }) {
  const [message, setMessage] = useState('');
  const submit = () => {
    const next = message.trim();
    if (!next || disabled) return;
    onSubmit(next);
    setMessage('');
  };

  return (
    <form className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-3 shadow-sm" aria-label="Project Kadode AI composer" onSubmit={(event) => { event.preventDefault(); submit(); }}>
      <label htmlFor="project-composer" className="sr-only">このプロジェクトについて Kadode AI に尋ねる</label>
      <textarea id="project-composer" disabled={disabled} className="min-h-24 w-full resize-none bg-transparent px-2 py-1 text-base leading-7 outline-none placeholder:text-[var(--color-text-muted)] disabled:cursor-wait" value={message} onChange={(event) => setMessage(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); submit(); } }} placeholder={disabled ? '会話を読み込んでいます…' : 'このプロジェクトについて、考えたことや確かめたいことを書いてください'} />
      <div className="flex items-center justify-between gap-2 border-t border-[var(--color-border-subtle)] pt-2">
        <div className="flex items-center gap-1"><Button type="button" variant="ghost" disabled aria-label="資料を追加"><Paperclip className="size-4" /></Button><Button type="button" variant="ghost" disabled className="gap-1.5 text-xs" aria-label="AIで補完"><Sparkles className="size-3.5" />補完</Button></div>
        <Button type="submit" disabled={disabled || !message.trim()} className="min-h-9 rounded-lg px-3" aria-label="送信"><ArrowUp className="size-4" /></Button>
      </div>
    </form>
  );
}

export function ProjectSurface({ state = 'populated', project: projectFixture = demoProjectFixture, adoptedProject, conversationRepository }) {
  const [messages, setMessages] = useState([]);
  const [phase, setPhase] = useState('loading');
  const [conversationError, setConversationError] = useState('');
  const [exported, setExported] = useState(false);
  const [decisionFilter, setDecisionFilter] = useState('all');
  const resolvedProject = adoptedProject ? { name: adoptedProject.title, status: adoptedProject.status, overview: adoptedProject.inference, decisions: adoptedProject.reason ? [{ id: `${adoptedProject.id}-adoption`, kind: 'adopted', date: '', title: adoptedProject.title, reason: adoptedProject.reason }] : [], sections: Object.fromEntries(sectionLabels.map((label) => [label, { status: '未確認', summary: 'この観点はProjectで検討します。', evidence: adoptedProject.fact, unknown: 'Projectでの会話から仮説を更新します。' }])) } : projectFixture;
  const project = resolvedProject;
  const projectId = adoptedProject?.id ?? projectFixture.datasetId ?? 'demo-project';
  const ownerId = adoptedProject?.ownerId ?? 'local-owner';
  const spaceId = adoptedProject?.spaceId ?? 'local-space';
  const browserRepository = useMemo(() => createProjectConversationRepository({ ownerId, spaceId, projectId }), [ownerId, projectId, spaceId]);
  const repository = conversationRepository ?? browserRepository;
  const loadId = useRef(0);

  useEffect(() => {
    const request = ++loadId.current;
    setPhase('loading');
    setConversationError('');
    Promise.resolve(repository.load()).then((saved) => {
      if (request !== loadId.current) return;
      setMessages(saved);
      setPhase('ready');
    }).catch(() => {
      if (request !== loadId.current) return;
      setConversationError('会話を読み込めませんでした。ページを再読み込みしてください。');
      setPhase('error');
    });
  }, [repository]);

  async function send(message) {
    if (phase !== 'ready') return;
    const next = [...messages, { id: `user-${Date.now()}`, role: 'user', content: message }, { id: `assistant-${Date.now()}`, role: 'assistant', content: nextProjectAssistantReply(project.name, message) }];
    try {
      const saved = await repository.save(next);
      setMessages(saved);
      setConversationError('');
    } catch {
      setConversationError('会話を保存できませんでした。もう一度お試しください。');
    }
  }

  const status = { loading: '読み込み中', error: '確認が必要', empty: '検討中', populated: project.status }[state];
  const decisions = project.decisions?.filter((decision) => decisionFilter === 'all' || decision.kind === decisionFilter) ?? [];
  return <section aria-labelledby="project-surface-heading" className="mx-auto w-full max-w-6xl pb-12">
    <header className="flex flex-wrap items-start justify-between gap-4 border-b border-[var(--color-border-subtle)] pb-6"><div><p className="text-xs font-bold uppercase tracking-[0.16em] text-[var(--color-text-muted)]">PROJECT</p><div className="mt-2 flex flex-wrap items-center gap-3"><h1 id="project-surface-heading" className="text-3xl font-semibold tracking-tight">{project.name}</h1><Badge variant="outline">{status}</Badge></div><p className="mt-2 max-w-3xl text-sm leading-6 text-[var(--color-text-muted)]">{project.overview}</p></div><Button type="button" variant="secondary" className="gap-2" onClick={() => setExported(true)}><FileText className="size-4" />事業計画書をエクスポート</Button></header>
    {exported && <p className="mt-3 text-sm text-[var(--color-text-muted)]" role="status">事業計画書の下書きを用意しました。内容を確認してから書き出せます。</p>}
    <div className="mt-7 grid gap-8 lg:grid-cols-[minmax(0,1.3fr)_minmax(19rem,.7fr)]"><div className="min-w-0 space-y-7"><div><div className="mb-3 flex items-center justify-between gap-3"><h2 className="text-base font-semibold">Kadode AI と検討する</h2><span className="text-xs text-[var(--color-text-muted)]">このProjectの文脈だけを使います</span></div>{conversationError && <p role="alert" className="mb-3 text-sm text-red-700">{conversationError}</p>}{messages.length > 0 && <ol className="mb-4 space-y-3" aria-label="Project conversation">{messages.map((message) => <li key={message.id} data-message-role={message.role} className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-6 ${message.role === 'user' ? 'ml-auto bg-[var(--color-muted)]' : 'bg-[var(--color-surface-raised)] ring-1 ring-[var(--color-border-subtle)]'}`}>{message.content}</li>)}</ol>}<Composer disabled={phase !== 'ready'} onSubmit={send} /></div>
      <div aria-labelledby="project-questions-heading"><div className="mb-3 flex items-baseline justify-between gap-3"><h2 id="project-questions-heading" className="text-base font-semibold">事業を深める</h2><p className="text-xs text-[var(--color-text-muted)]">根拠と未確認を分けて検討</p></div><div className="grid gap-3 md:grid-cols-2">{sectionLabels.map((label) => { const item = project.sections[label]; return <Card key={label} data-project-question="true" className="p-4"><div className="flex items-baseline justify-between gap-3"><h3 className="font-semibold">{label}</h3><Badge variant="secondary">{item.status}</Badge></div><p className="mt-3 text-sm leading-6">{state === 'loading' ? '読み込み中です。' : state === 'error' ? '確認が必要です。' : item.summary}</p><dl className="mt-4 space-y-2 border-t border-[var(--color-border-subtle)] pt-3 text-xs leading-5"><div><dt className="font-semibold text-[var(--color-text-muted)]">根拠</dt><dd>{item.evidence}</dd></div><div><dt className="font-semibold text-[var(--color-text-muted)]">未確認</dt><dd>{item.unknown}</dd></div></dl></Card>; })}</div></div></div>
      <aside className="space-y-4" aria-labelledby="decision-history-heading"><div className="flex items-center justify-between gap-2"><h2 id="decision-history-heading" className="text-base font-semibold">判断・意思決定</h2><select aria-label="履歴を絞り込む" value={decisionFilter} onChange={(event) => setDecisionFilter(event.target.value)} className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-raised)] px-2 py-1 text-xs"><option value="all">すべて</option><option value="adopted">採用</option></select></div><Card className="divide-y divide-[var(--color-border-subtle)]">{decisions.length ? decisions.map((decision) => <div key={decision.id} className="p-4"><div className="flex items-center justify-between gap-2"><Badge variant={decision.kind === 'adopted' ? 'default' : 'outline'}>{decision.kind}</Badge><time className="text-xs text-[var(--color-text-muted)]">{decision.date}</time></div><p className="mt-3 text-sm font-medium">{decision.title}</p><p className="mt-1 text-xs leading-5 text-[var(--color-text-muted)]">{decision.reason}</p></div>) : <p className="p-4 text-sm text-[var(--color-text-muted)]">この条件の履歴はありません。</p>}</Card></aside></div>
  </section>;
}
