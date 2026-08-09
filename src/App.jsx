import { useEffect, useRef, useState } from 'react';

import { IdeaCandidateWorkspace } from './components/IdeaCandidateWorkspace';
import { ModelSelector } from './components/ModelSelector';
import { PlanSelection } from './components/PlanSelection';
import { createLocalPlanRepository } from './components/planSubscriptionRepository';
import { createBrowserProfileRepository, UserProfileInterview } from './components/UserProfileInterview';
import { WorkspaceShell } from './components/WorkspaceShell';

export const WORKSPACE_NAV = [{ id: 'home', label: 'Home' }, { id: 'project', label: 'Project' }, { id: 'knowledge', label: 'Knowledge' }];
export const SELECTED_SURFACE_STORAGE_KEY = 'kadode:selected-surface';

export function readSelectedSurface(storage = globalThis.sessionStorage) {
  try {
    const selected = storage?.getItem(SELECTED_SURFACE_STORAGE_KEY);
    return WORKSPACE_NAV.some(({ id }) => id === selected) ? selected : 'home';
  } catch {
    return 'home';
  }
}

function persistSelectedSurface(surface, storage = globalThis.sessionStorage) {
  if (!WORKSPACE_NAV.some(({ id }) => id === surface)) return;
  try { storage?.setItem(SELECTED_SURFACE_STORAGE_KEY, surface); } catch { /* session storage is optional */ }
}

function HomeConversationSurface() {
  return (
    <section aria-labelledby="home-heading" className="max-w-3xl">
      <p className="text-xs font-bold uppercase tracking-[0.16em] text-stone-500">Home</p>
      <h1 id="home-heading" className="mt-2 text-2xl font-semibold tracking-tight">Kadode AI</h1>
      <p className="mt-2 max-w-2xl text-sm leading-6 text-stone-600">着想や経験を話しながら整理し、確認してから次の検討へ進めます。</p>
      <form className="mt-6 rounded-2xl border border-stone-300 bg-white p-3">
        <label htmlFor="home-composer" className="sr-only">AIへのメッセージ</label>
        <textarea id="home-composer" aria-describedby="home-composer-hint" className="min-h-24 w-full resize-y p-2 text-base leading-6 outline-none" placeholder="アイデアを話してみる" />
        <p id="home-composer-hint" className="mt-2 text-xs text-stone-500">Enterで送信、Shift+Enterで改行</p>
        <div className="mt-2 flex justify-end"><button type="button" className="min-h-11 rounded-full bg-stone-900 px-5 py-2 text-sm font-bold text-white">送信</button></div>
      </form>
    </section>
  );
}

function PlaceholderSurface({ name, description }) {
  return <section aria-labelledby={`${name.toLowerCase()}-heading`} className="max-w-3xl"><p className="text-xs font-bold uppercase tracking-[0.16em] text-stone-500">{name}</p><h1 id={`${name.toLowerCase()}-heading`} className="mt-2 text-2xl font-semibold tracking-tight">{name}</h1><p className="mt-2 max-w-2xl text-sm leading-6 text-stone-600">{description}</p></section>;
}

function IdeaWorkspace() {
  return (
    <div className="max-w-4xl">
      <section aria-labelledby="idea-heading">
        <h1 id="idea-heading" className="page-title">事業のタネ</h1>
        <p className="mt-2 max-w-2xl leading-7 text-stone-700">着想や経験を話しながら整理し、確認してから候補として保存します。</p>
        <div className="mt-6"><IdeaCandidateWorkspace /></div>
      </section>
    </div>
  );
}

function ProfileLoadFailure({ onRetry }) {
  return (
    <section className="kadode-dialog-panel w-full min-w-0 max-w-full overflow-hidden rounded-3xl p-6 shadow-xl sm:max-w-2xl" aria-labelledby="profile-load-error-heading">
      <p className="kadode-dialog-kicker font-bold">あなたの情報</p>
      <h2 id="profile-load-error-heading" className="mt-2 text-2xl font-bold">読み込めませんでした</h2>
      <p className="mt-4 leading-7">保存済みの情報を守るため、入力フォームは表示していません。接続を確認して再試行してください。</p>
      <button type="button" onClick={onRetry} className="kadode-dialog-submit mt-5 rounded-full px-5 py-3 font-bold">再試行</button>
    </section>
  );
}

export function App({ profileRepository }) {
  const [activeWorkspace, setActiveWorkspace] = useState(() => readSelectedSurface());
  const [profileOpen, setProfileOpen] = useState(false);
  const [profileDialogDismissed, setProfileDialogDismissed] = useState(false);
  const [profileHydration, setProfileHydration] = useState({ phase: 'loading', profile: null });
  const [profileLoadAttempt, setProfileLoadAttempt] = useState(0);
  const repositoryRef = useRef(null);
  if (!repositoryRef.current) repositoryRef.current = createLocalPlanRepository();
  const profileRepositoryRef = useRef(null);
  const profileDialogDismissedRef = useRef(false);
  if (!profileRepositoryRef.current) profileRepositoryRef.current = profileRepository ?? createBrowserProfileRepository();
  const [subscription, setSubscription] = useState(() => repositoryRef.current.getSubscription());
  const profileComplete = profileHydration.phase === 'ready' && profileHydration.profile?.status === 'completed';

  useEffect(() => { persistSelectedSurface(activeWorkspace); }, [activeWorkspace]);

  useEffect(() => {
    let mounted = true;
    profileRepositoryRef.current.load()
      .then((profile) => {
        if (!mounted) return;
        setProfileHydration({ phase: 'ready', profile });
        setProfileOpen(!profileDialogDismissedRef.current && profile?.status !== 'completed');
      })
      .catch(() => {
        if (mounted) setProfileHydration({ phase: 'error', profile: null });
      });
    return () => { mounted = false; };
  }, [profileLoadAttempt]);

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
    const closeProfile = (event) => {
      if (event.key === 'Escape') { profileDialogDismissedRef.current = true; setProfileDialogDismissed(true); setProfileOpen(false); }
    };
    window.addEventListener('keydown', closeProfile);
    return () => window.removeEventListener('keydown', closeProfile);
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

  function retryProfileLoad() {
    profileDialogDismissedRef.current = false;
    setProfileDialogDismissed(false);
    setProfileHydration({ phase: 'loading', profile: null });
    setProfileOpen(false);
    setProfileLoadAttempt((attempt) => attempt + 1);
  }

  function completeProfile(profile) {
    setProfileHydration({ phase: 'ready', profile });
    setProfileOpen(false);
  }

  function workspaceContent() {
    if (activeWorkspace === 'home') return <HomeConversationSurface />;
    if (activeWorkspace === 'project') return <PlaceholderSurface name="Project" description="プロジェクトの作業面は、次の実装で接続します。" />;
    if (activeWorkspace === 'knowledge') return <PlaceholderSurface name="Knowledge" description="Knowledgeの参照面は、次の実装で接続します。" />;
    if (activeWorkspace === 'settings') return <div className="max-w-4xl space-y-6"><PlanSelection currentPlan={subscription.plan} onApplyPlan={updatePlan} /><ModelSelector plan={subscription.plan} selectedModelKey={subscription.modelKey} selectedReasoningMode={subscription.reasoningMode} onModelChange={updateModel} onReasoningModeChange={updateReasoning} /></div>;
    return <IdeaWorkspace />;
  }

  return (
    <main className="kadode-shell">
      <WorkspaceShell activePage={activeWorkspace} onSelect={setActiveWorkspace} currentPlan={subscription.plan}>
        <header className="kadode-header border-b"><div className="flex min-h-12 min-w-0 items-center justify-between gap-4 px-5 py-3"><strong className="shrink-0 text-lg tracking-tight">Kadode</strong><span className="rounded-full border border-stone-300 px-2 py-1 text-xs font-semibold text-stone-600">local / fake モード</span></div></header>
        <div className="px-5 py-6 sm:py-8">{workspaceContent()}</div>
      </WorkspaceShell>
      {profileHydration.phase === 'ready' && <button type="button" onClick={() => { profileDialogDismissedRef.current = false; setProfileDialogDismissed(false); setProfileOpen(true); }} className="kadode-profile-button fixed bottom-5 right-5 rounded-full px-5 py-3 font-bold shadow-lg">あなたの情報を{profileComplete ? '更新' : '入力'}</button>}
      {((profileHydration.phase === 'loading' && !profileDialogDismissed) || profileHydration.phase === 'error' || profileOpen) && <div className="kadode-dialog-backdrop fixed inset-0 z-10 grid grid-cols-[minmax(0,1fr)] place-items-end overflow-x-hidden p-3 sm:place-items-center sm:p-6" role="dialog" aria-modal="true" aria-label="あなたの情報">{profileHydration.phase === 'loading' ? <div className="kadode-dialog-panel w-full rounded-3xl p-6 shadow-xl sm:max-w-2xl">準備しています…</div> : profileHydration.phase === 'error' ? <ProfileLoadFailure onRetry={retryProfileLoad} /> : <UserProfileInterview initialProfile={profileHydration.profile} repository={profileRepositoryRef.current} onClose={() => setProfileOpen(false)} onComplete={completeProfile} />}</div>}
    </main>
  );
}
