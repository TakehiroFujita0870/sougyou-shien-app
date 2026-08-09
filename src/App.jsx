import { useEffect, useRef, useState } from 'react';

import { FileLibrary } from './components/FileLibrary';
import { IdeaCandidateWorkspace } from './components/IdeaCandidateWorkspace';
import { ModelSelector } from './components/ModelSelector';
import { PlanSelection } from './components/PlanSelection';
import { createLocalPlanRepository } from './components/planSubscriptionRepository';
import { ResearchWorkspace } from './components/ResearchWorkspace';
import { createBrowserProfileRepository, UserProfileInterview } from './components/UserProfileInterview';
import { WorkspaceShell } from './components/WorkspaceShell';

export const WORKSPACE_NAV = [{ id: 'ideas', label: '事業のタネ' }, { id: 'research', label: '横断調査' }, { id: 'files', label: '資料' }, { id: 'settings', label: '設定' }];

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
  const [activeWorkspace, setActiveWorkspace] = useState('ideas');
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
    if (activeWorkspace === 'chat') return <section><h1 className="page-title">AIチャット</h1><p>プロフィールと現在の事業のタネを文脈にして対話できます。</p></section>;
    if (activeWorkspace === 'projects') return <section><h1 className="page-title">プロジェクト</h1><p>事業のタネに紐づく作業をまとめます。</p></section>;
    if (activeWorkspace === 'search') return <section><h1 className="page-title">検索</h1><p>ワークスペース内の情報を検索します。</p></section>;
    if (activeWorkspace === 'research') return <ResearchWorkspace />;
    if (activeWorkspace === 'files') return <FileLibrary />;
    if (activeWorkspace === 'settings') return <div className="max-w-4xl space-y-6"><PlanSelection currentPlan={subscription.plan} onApplyPlan={updatePlan} /><ModelSelector plan={subscription.plan} selectedModelKey={subscription.modelKey} selectedReasoningMode={subscription.reasoningMode} onModelChange={updateModel} onReasoningModeChange={updateReasoning} /></div>;
    return <IdeaWorkspace />;
  }

  return (
    <main className="kadode-shell">
      <WorkspaceShell activePage={activeWorkspace} onSelect={setActiveWorkspace} currentPlan={subscription.plan}>
        <header className="kadode-header border-b"><div className="flex min-w-0 items-center justify-between gap-4 px-5 py-5"><strong className="shrink-0 text-2xl tracking-tight">Kadode</strong><span className="min-w-0 break-words text-right text-sm font-medium text-[color:var(--color-text-muted)]">アイデアを、構造で育てる。</span></div></header>
        <div className="px-5 py-6 sm:py-10"><p className="kadode-notice mb-6 rounded-2xl border px-4 py-3 text-sm leading-6"><strong>local / fake モード</strong> — このMVPでは外部サービスへ接続・送信しません。</p>{workspaceContent()}</div>
      </WorkspaceShell>
      {profileHydration.phase === 'ready' && <button type="button" onClick={() => { profileDialogDismissedRef.current = false; setProfileDialogDismissed(false); setProfileOpen(true); }} className="kadode-profile-button fixed bottom-5 right-5 rounded-full px-5 py-3 font-bold shadow-lg">あなたの情報を{profileComplete ? '更新' : '入力'}</button>}
      {((profileHydration.phase === 'loading' && !profileDialogDismissed) || profileHydration.phase === 'error' || profileOpen) && <div className="kadode-dialog-backdrop fixed inset-0 z-10 grid grid-cols-[minmax(0,1fr)] place-items-end overflow-x-hidden p-3 sm:place-items-center sm:p-6" role="dialog" aria-modal="true" aria-label="あなたの情報">{profileHydration.phase === 'loading' ? <div className="kadode-dialog-panel w-full rounded-3xl p-6 shadow-xl sm:max-w-2xl">準備しています…</div> : profileHydration.phase === 'error' ? <ProfileLoadFailure onRetry={retryProfileLoad} /> : <UserProfileInterview initialProfile={profileHydration.profile} repository={profileRepositoryRef.current} onClose={() => setProfileOpen(false)} onComplete={completeProfile} />}</div>}
    </main>
  );
}
