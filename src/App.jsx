import { useEffect, useRef, useState } from 'react';

import { FileLibrary } from './components/FileLibrary';
import { IdeaCandidateWorkspace } from './components/IdeaCandidateWorkspace';
import { IdeaForm } from './components/IdeaForm';
import { ModelSelector } from './components/ModelSelector';
import { PlanSelection } from './components/PlanSelection';
import { createLocalPlanRepository } from './components/planSubscriptionRepository';
import { ResearchWorkspace } from './components/ResearchWorkspace';
import { UserProfileInterview } from './components/UserProfileInterview';
import { AI_COPY_CATALOG } from './copy/aiVoice';

export const WORKSPACE_NAV = [
  { id: 'ideas', label: 'アイデア' },
  { id: 'research', label: '横断調査' },
  { id: 'files', label: '資料' },
  { id: 'settings', label: '設定' },
];

function Navigation({ activeWorkspace, onSelect }) {
  return (
    <nav aria-label="ワークスペース" className="kadode-navigation min-w-0 max-w-full overflow-hidden border-b">
      <div className="mx-auto flex min-w-0 max-w-6xl gap-2 overflow-x-auto px-5 py-3 sm:px-8">
        {WORKSPACE_NAV.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => onSelect(item.id)}
            aria-current={activeWorkspace === item.id ? 'page' : undefined}
            className="kadode-nav-button min-h-11 shrink-0 rounded-full px-4 py-2 text-sm font-bold"
          >
            {item.label}
          </button>
        ))}
      </div>
    </nav>
  );
}

function IdeaWorkspace({ idea, onReset, onSubmit, profileReady }) {
  const copy = AI_COPY_CATALOG.welcome;

  return (
    <div className="max-w-4xl">
      <section aria-labelledby="idea-heading">
        <p className="text-sm font-bold text-emerald-700">最初の一案</p>
        <h1 id="idea-heading" className="mt-3 text-4xl font-bold tracking-tight sm:text-6xl">{copy.heading}</h1>
        <p className="mt-5 max-w-2xl text-base leading-7 text-stone-700 sm:text-lg">{copy.body}</p>
        <div className="mt-8">
          {idea ? <article className="kadode-card rounded-3xl border p-6 shadow-sm"><p className="kadode-card-kicker text-xs font-bold tracking-[0.16em]">仮説カード・下書き</p><h2 className="mt-2 text-2xl font-bold">{idea.title}</h2><p className="mt-3 leading-7 text-[color:var(--color-text-muted)]">{idea.ideaSummary}</p><dl className="kadode-card-detail mt-5 rounded-2xl p-4"><dt className="text-xs font-bold text-[color:var(--color-text-muted)]">誰の、何のペインか</dt><dd className="mt-1 leading-6">{idea.painStatement}</dd></dl><p className="mt-4 text-sm text-[color:var(--color-text-muted)]">現在はブラウザ内の下書きです。外部サービスには送信していません。</p><button type="button" onClick={onReset} className="kadode-card-button mt-5 rounded-full border px-5 py-2.5 text-sm font-bold">入力し直す</button></article> : <IdeaForm onSubmit={onSubmit} />}
        </div>
        <div className="mt-8"><IdeaCandidateWorkspace profileReady={profileReady} /></div>
      </section>
    </div>
  );
}

export function App() {
  const [idea, setIdea] = useState(null);
  const [activeWorkspace, setActiveWorkspace] = useState('ideas');
  const [profileOpen, setProfileOpen] = useState(true);
  const [profileComplete, setProfileComplete] = useState(false);
  const repositoryRef = useRef(null);
  if (!repositoryRef.current) repositoryRef.current = createLocalPlanRepository();
  const [subscription, setSubscription] = useState(() => repositoryRef.current.getSubscription());

  useEffect(() => {
    const shortcut = (event) => {
      if (!event.altKey || !event.shiftKey || event.ctrlKey || event.metaKey) return;
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement || event.target?.isContentEditable) return;
      const workspace = WORKSPACE_NAV[Number(event.key) - 1];
      if (!workspace) return;
      event.preventDefault();
      setActiveWorkspace(workspace.id);
    };
    window.addEventListener('keydown', shortcut);
    return () => window.removeEventListener('keydown', shortcut);
  }, []);

  useEffect(() => {
    if (activeWorkspace === 'settings') document.getElementById('model')?.focus();
  }, [activeWorkspace, subscription.plan]);

  function updatePlan(plan) {
    setSubscription(repositoryRef.current.applyPlan(plan, subscription));
  }

  function updateModel(modelKey) {
    setSubscription((current) => ({ ...current, modelKey, reasoningMode: null }));
  }

  function updateReasoning(reasoningMode) {
    setSubscription((current) => ({ ...current, reasoningMode }));
  }

  function workspaceContent() {
    if (activeWorkspace === 'research') return <ResearchWorkspace />;
    if (activeWorkspace === 'files') return <FileLibrary />;
    if (activeWorkspace === 'settings') return <div className="max-w-4xl space-y-6"><PlanSelection currentPlan={subscription.plan} onApplyPlan={updatePlan} /><ModelSelector plan={subscription.plan} selectedModelKey={subscription.modelKey} selectedReasoningMode={subscription.reasoningMode} onModelChange={updateModel} onReasoningModeChange={updateReasoning} /></div>;
    return <IdeaWorkspace idea={idea} onReset={() => setIdea(null)} onSubmit={setIdea} profileReady={profileComplete} />;
  }

  return (
    <main className="kadode-shell">
      <header className="kadode-header border-b"><div className="mx-auto flex min-w-0 max-w-6xl items-center justify-between gap-4 px-5 py-5 sm:px-8"><strong className="shrink-0 text-2xl tracking-tight">Kadode</strong><span className="min-w-0 break-words text-right text-sm font-medium text-[color:var(--color-text-muted)]">アイデアを、構造で育てる。</span></div></header>
      <Navigation activeWorkspace={activeWorkspace} onSelect={setActiveWorkspace} />
      <div className="mx-auto max-w-6xl px-5 py-6 sm:px-8 sm:py-10"><p className="kadode-notice mb-6 rounded-2xl border px-4 py-3 text-sm leading-6"><strong>local / fake モード</strong> — このMVPでは外部サービスへ接続・送信しません。</p>{workspaceContent()}</div>
      <button type="button" onClick={() => setProfileOpen(true)} className="kadode-profile-button fixed bottom-5 right-5 rounded-full px-5 py-3 font-bold shadow-lg">あなたの情報を{profileComplete ? '更新' : '入力'}</button>
      {profileOpen && <div className="kadode-dialog-backdrop fixed inset-0 z-10 grid grid-cols-[minmax(0,1fr)] place-items-end overflow-x-hidden p-3 sm:place-items-center sm:p-6" role="dialog" aria-modal="true" aria-label="あなたの情報"><UserProfileInterview onClose={() => setProfileOpen(false)} onComplete={() => setProfileComplete(true)} /></div>}
    </main>
  );
}
