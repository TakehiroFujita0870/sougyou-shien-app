import { useCallback, useEffect, useRef, useState } from 'react';

import { createHomeConversationRepository, HomeSupervisor } from './components/HomeSupervisor';
import { KnowledgeSurface } from './components/KnowledgeSurface';
import { PlanSelection } from './components/PlanSelection';
import { createLocalPlanRepository } from './components/planSubscriptionRepository';
import { createBrowserProfileRepository, UserProfileInterview } from './components/UserProfileInterview';
import { WorkspaceShell } from './components/WorkspaceShell';
import { createHomeModelRepository, getHomeModels } from './components/homeModelRepository';
import { ProjectSurface, projectEvaluationTabs } from './components/ProjectSurface';
import { createAdoptedProjectRepository } from './components/adoptedProjectRepository';
import { useHydratedResource } from './runtime/useHydratedResource';
import { createSidebarPortfolioRepository } from './components/sidebarPortfolioRepository';
import knowledgeDemoFixture from './fixtures/knowledge-admin-demo.json';

export const WORKSPACE_NAV = [{ id: 'home', label: 'ホーム' }, { id: 'project', label: 'プロジェクト' }, { id: 'knowledge', label: 'ナレッジ' }];
export const SELECTED_SURFACE_STORAGE_KEY = 'kadode:selected-surface';

function portfolioMessageId(prefix, value) {
  let hash = 2166136261;
  for (const character of String(value)) hash = Math.imul(hash ^ character.charCodeAt(0), 16777619);
  return `${prefix}:${(hash >>> 0).toString(36)}`;
}

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

function PlaceholderSurface({ name, description, project }) {
  if (name === 'Project' && project) return <section aria-labelledby="project-heading" className="max-w-3xl"><p className="text-xs font-bold uppercase tracking-[0.16em] text-stone-500">Project</p><h1 id="project-heading" className="mt-2 text-2xl font-semibold tracking-tight">採用したプロジェクト</h1><article className="mt-6 rounded-2xl border border-stone-300 bg-white p-4"><p><strong>事実:</strong> {project.fact}</p><p><strong>推論:</strong> {project.inference}</p><p><strong>状態:</strong> 採用済み</p></article></section>;
  return <section aria-labelledby={`${name.toLowerCase()}-heading`} className="max-w-3xl"><p className="text-xs font-bold uppercase tracking-[0.16em] text-stone-500">{name}</p><h1 id={`${name.toLowerCase()}-heading`} className="mt-2 text-2xl font-semibold tracking-tight">{name}</h1><p className="mt-2 max-w-2xl text-sm leading-6 text-stone-600">{description}</p></section>;
}

function IdeaWorkspace({ repository, onProjectAdopt, modelKey, models, onModelChange }) {
  return <div className="max-w-6xl"><HomeSupervisor repository={repository} onProjectAdopt={onProjectAdopt} modelKey={modelKey} models={models} onModelChange={onModelChange} /></div>;
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

export function App({ profileRepository, adoptedProjectRepository, homeConversationRepository, sidebarPortfolioRepository }) {
  const [activeWorkspace, setActiveWorkspace] = useState(() => readSelectedSurface());
  const [profileOpen, setProfileOpen] = useState(false);
  const [profileDialogDismissed, setProfileDialogDismissed] = useState(false);
  const repositoryRef = useRef(null);
  if (!repositoryRef.current) repositoryRef.current = createLocalPlanRepository();
  const homeModelRepositoryRef = useRef(null);
  if (!homeModelRepositoryRef.current) homeModelRepositoryRef.current = createHomeModelRepository();
  const profileRepositoryRef = useRef(null);
  const adoptedProjectRepositoryRef = useRef(null);
  const profileDialogDismissedRef = useRef(false);
  if (!profileRepositoryRef.current) profileRepositoryRef.current = profileRepository ?? createBrowserProfileRepository();
  if (!adoptedProjectRepositoryRef.current) adoptedProjectRepositoryRef.current = adoptedProjectRepository ?? createAdoptedProjectRepository();
  const profileHydration = useHydratedResource(profileRepositoryRef.current);
  const adoptedProjectHydration = useHydratedResource(adoptedProjectRepositoryRef.current);
  const [subscription, setSubscription] = useState(() => repositoryRef.current.getSubscription());
  const [homeModelKey, setHomeModelKey] = useState(() => homeModelRepositoryRef.current.get());
  const portfolioRepositoryRef = useRef(null);
  if (!portfolioRepositoryRef.current) portfolioRepositoryRef.current = sidebarPortfolioRepository ?? createSidebarPortfolioRepository();
  const [portfolio, setPortfolio] = useState({ home: [], project: [], knowledge: [] });
  const [portfolioHydrated, setPortfolioHydrated] = useState(false);
  const [portfolioError, setPortfolioError] = useState('');
  const [homeConversationRevision, setHomeConversationRevision] = useState(0);
  const [activeHomeConversationId, setActiveHomeConversationId] = useState('');
  const [projectTargetView, setProjectTargetView] = useState('');
  const rawHomeConversationRepositoryRef = useRef(null);
  if (!rawHomeConversationRepositoryRef.current) rawHomeConversationRepositoryRef.current = homeConversationRepository ?? createHomeConversationRepository({ ownerId: 'local-owner', spaceId: 'local-space' });
  const trackedHomeConversationRepositoryRef = useRef(null);
  if (!trackedHomeConversationRepositoryRef.current) trackedHomeConversationRepositoryRef.current = {
    load: () => rawHomeConversationRepositoryRef.current.load(),
    loadDraft: () => rawHomeConversationRepositoryRef.current.loadDraft?.() ?? Promise.resolve(''),
    saveDraft: (value) => rawHomeConversationRepositoryRef.current.saveDraft?.(value) ?? Promise.resolve(value),
    save: async (value) => {
      const saved = await rawHomeConversationRepositoryRef.current.save(value);
      const userMessages = saved.messages?.filter((entry) => entry.role === 'user') ?? [];
      const latestUserMessage = userMessages.at(-1)?.content?.trim();
      if (latestUserMessage) {
        const conversationId = portfolioMessageId(`home:${userMessages.length}`, latestUserMessage);
        const nextPortfolio = await portfolioRepositoryRef.current.upsertAndActivateHome({ id: conversationId, title: latestUserMessage.slice(0, 80), snapshot: saved, updatedAt: Date.now() });
        setPortfolio(nextPortfolio);
        setActiveHomeConversationId(conversationId);
        setPortfolioError('');
      }
      return saved;
    },
  };

  useEffect(() => { persistSelectedSurface(activeWorkspace); }, [activeWorkspace]);
  useEffect(() => { repositoryRef.current.load().then(setSubscription); }, []);
  useEffect(() => { homeModelRepositoryRef.current.load().then(setHomeModelKey); }, []);
  useEffect(() => {
    let active = true;
    portfolioRepositoryRef.current.load().then((value) => {
      if (!active) return;
      setPortfolio(value);
      setActiveHomeConversationId(value.activeHomeId);
      setPortfolioHydrated(true);
    }).catch(() => { if (active) setPortfolioHydrated(true); });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    let active = true;
    async function mirrorPersistedContext() {
      const home = await rawHomeConversationRepositoryRef.current.load();
      const userMessages = home.messages?.filter((entry) => entry.role === 'user') ?? [];
      const latestUserMessage = userMessages.at(-1)?.content?.trim();
      if (latestUserMessage) {
        const conversationId = portfolioMessageId(`home:${userMessages.length}`, latestUserMessage);
        const currentPortfolio = await portfolioRepositoryRef.current.load();
        const serializedHome = JSON.stringify(home);
        const matchingRecord = currentPortfolio.home.find((item) => item.snapshot && JSON.stringify(item.snapshot) === serializedHome)
          ?? currentPortfolio.home.find((item) => item.id === conversationId);
        const savedHome = matchingRecord
          ? await portfolioRepositoryRef.current.setActiveHome(matchingRecord.id)
          : await portfolioRepositoryRef.current.upsertAndActivateHome({ id: conversationId, title: latestUserMessage.slice(0, 80), snapshot: home, updatedAt: Date.now() });
        if (active) setPortfolio(savedHome);
        if (active) setActiveHomeConversationId(matchingRecord?.id ?? conversationId);
      }
      if (knowledgeDemoFixture?.asset) {
        const asset = knowledgeDemoFixture.asset;
        const savedKnowledge = await portfolioRepositoryRef.current.ensure('knowledge', { id: asset.id, title: asset.name, updatedAt: Date.now() });
        if (active) setPortfolio(savedKnowledge);
      }
    }
    void mirrorPersistedContext().catch(() => { if (active) setPortfolioError('履歴を読み込めませんでした。ページを再読み込みして、もう一度お試しください。'); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!portfolioHydrated) return;
    const archivedHome = activeWorkspace === 'home' && portfolio.home.some((item) => item.id === activeHomeConversationId && item.archived);
    const archivedProject = activeWorkspace === 'project' && portfolio.project.some((item) => item.id === adoptedProjectHydration.value?.id && item.archived);
    if (archivedHome || archivedProject) setActiveWorkspace('knowledge');
  }, [activeHomeConversationId, activeWorkspace, adoptedProjectHydration.value?.id, portfolio, portfolioHydrated]);

  useEffect(() => {
    if (profileHydration.phase === 'ready') {
      setProfileOpen(false);
    }
  }, [profileHydration.phase, profileHydration.value]);

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

  function updatePlan(plan) {
    const next = repositoryRef.current.applyPlan(plan, subscription);
    setSubscription(next);
    void repositoryRef.current.save(next);
  }
  function updateModel(modelKey) {
    setHomeModelKey(modelKey);
    void homeModelRepositoryRef.current.save(modelKey);
  }

  function retryProfileLoad() {
    profileDialogDismissedRef.current = false;
    setProfileDialogDismissed(false);
    setProfileOpen(false);
    profileHydration.retry();
  }

  function completeProfile(profile) {
    profileHydration.replaceReady(profile);
    setProfileOpen(false);
  }

  const adoptProject = useCallback(async (candidate) => {
    if (adoptedProjectHydration.phase === 'ready' && adoptedProjectHydration.value?.id === candidate?.id) {
      setActiveWorkspace('project');
      return;
    }
    try {
      const project = await adoptedProjectRepositoryRef.current.saveAdopted(candidate);
      adoptedProjectHydration.replaceReady(project);
      const nextPortfolio = await portfolioRepositoryRef.current.upsert('project', { id: project.id, title: project.title, snapshot: project, updatedAt: Date.now() });
      setPortfolio(nextPortfolio);
      setActiveWorkspace('project');
    } catch {
      // Home retains its own decision state if the Project mirror cannot be persisted.
    }
  }, [adoptedProjectHydration.phase, adoptedProjectHydration.replaceReady, adoptedProjectHydration.value]);

  function workspaceContent() {
    const availableProjects = adoptedProjectRepositoryRef.current.list?.() ?? (adoptedProjectHydration.value ? [adoptedProjectHydration.value] : []);
    const archivedHome = portfolio.home.some((item) => item.id === activeHomeConversationId && item.archived);
    const archivedProject = portfolio.project.some((item) => item.id === adoptedProjectHydration.value?.id && item.archived);
    if (portfolioHydrated && ((activeWorkspace === 'home' && archivedHome) || (activeWorkspace === 'project' && archivedProject))) return <KnowledgeSurface fixture={knowledgeDemoFixture} profile={profileHydration.value} archiveHistory={[...portfolio.home, ...portfolio.project].filter((item) => item.archived)} modelKey={homeModelKey} models={getHomeModels()} onModelChange={updateModel} />;
    if (activeWorkspace === 'home') return <IdeaWorkspace key={homeConversationRevision} repository={trackedHomeConversationRepositoryRef.current} modelKey={homeModelKey} models={getHomeModels()} onModelChange={updateModel} onProjectAdopt={adoptProject} />;
    if (activeWorkspace === 'project') {
      if (adoptedProjectHydration.phase === 'loading') return <section aria-live="polite" className="max-w-3xl py-10 text-sm text-[var(--color-text-muted)]">プロジェクトを読み込んでいます…</section>;
      return <ProjectSurface adoptedProject={adoptedProjectHydration.value} targetView={projectTargetView} onTargetViewHandled={() => setProjectTargetView('')} />;
    }
    if (activeWorkspace === 'knowledge') return <KnowledgeSurface fixture={knowledgeDemoFixture} profile={profileHydration.value} ownerId="local-owner" spaceId="local-space" availableProjects={availableProjects} allowedEvaluationViews={projectEvaluationTabs} archiveHistory={[...portfolio.home, ...portfolio.project].filter((item) => item.archived)} onOpenProject={async (projectId, evaluationView) => { const project = availableProjects.find((item) => item.id === projectId && item.ownerId === 'local-owner' && item.spaceId === 'local-space'); if (!project || !projectEvaluationTabs.includes(evaluationView)) return; try { const selected = await adoptedProjectRepositoryRef.current.selectCurrent?.(projectId) ?? project; adoptedProjectHydration.replaceReady(selected); setProjectTargetView(evaluationView); setPortfolioError(''); setActiveWorkspace('project'); } catch { setPortfolioError('Projectを開けませんでした。もう一度お試しください。'); } }} onAssetAdded={async (asset) => { const next = await portfolioRepositoryRef.current.ensure('knowledge', { id: asset.id, title: asset.name, unread: true, updatedAt: Date.now() }); setPortfolio(next); setPortfolioError(''); }} onSend={(value) => { void portfolioRepositoryRef.current.ensure('knowledge', { id: portfolioMessageId('knowledge:conversation', value), title: value.slice(0, 80), unread: true, updatedAt: Date.now() }).then((next) => { setPortfolio(next); setPortfolioError(''); }).catch(() => setPortfolioError('履歴を保存できませんでした。もう一度お試しください。')); }} modelKey={homeModelKey} models={getHomeModels()} onModelChange={updateModel} />;
    if (activeWorkspace === 'settings') return <div className="max-w-4xl space-y-6"><PlanSelection currentPlan={subscription.plan} onApplyPlan={updatePlan} /></div>;
    return <IdeaWorkspace key={homeConversationRevision} repository={trackedHomeConversationRepositoryRef.current} modelKey={homeModelKey} models={getHomeModels()} onModelChange={updateModel} />;
  }

  return (
    <main className="kadode-shell">
      <WorkspaceShell activePage={activeWorkspace} onSelect={(page) => { const archivedHome = page === 'home' && portfolio.home.some((item) => item.id === activeHomeConversationId && item.archived); const archivedProject = page === 'project' && portfolio.project.some((item) => item.id === adoptedProjectHydration.value?.id && item.archived); setActiveWorkspace(archivedHome || archivedProject ? 'knowledge' : page); }} portfolio={portfolio} portfolioError={portfolioError} onOpenPortfolioItem={async (type, entry) => { if (entry.archived) return; try { if (type === 'home' && entry.snapshot) { await rawHomeConversationRepositoryRef.current.save(entry.snapshot); const next = await portfolioRepositoryRef.current.setActiveHome(entry.id); setPortfolio(next); setActiveHomeConversationId(entry.id); setHomeConversationRevision((value) => value + 1); } if (type === 'project' && entry.snapshot) { const restored = await adoptedProjectRepositoryRef.current.saveAdopted(entry.snapshot); adoptedProjectHydration.replaceReady(restored); } if (type === 'knowledge') { const next = await portfolioRepositoryRef.current.markRead('knowledge', entry.id); setPortfolio(next); } setPortfolioError(''); setActiveWorkspace(type); } catch { setPortfolioError('履歴を開けませんでした。項目は削除されていません。もう一度お試しください。'); throw new Error('Portfolio item open failed'); } }} onArchive={async (type, id) => { try { const next = await portfolioRepositoryRef.current.archive(type, id); setPortfolio(next); setPortfolioError(''); setActiveWorkspace('knowledge'); return true; } catch { setPortfolioError('アーカイブできませんでした。項目はそのまま残っています。もう一度お試しください。'); return false; } }} onRestore={async (type, entry) => { let previous; let staged = false; try { if (type === 'home') { previous = await rawHomeConversationRepositoryRef.current.load(); await rawHomeConversationRepositoryRef.current.save(entry.snapshot); } else { previous = adoptedProjectHydration.value; await adoptedProjectRepositoryRef.current.saveAdopted(entry.snapshot); } staged = true; const restoredPortfolio = await portfolioRepositoryRef.current.restore(type, entry.id); if (type === 'home') { setActiveHomeConversationId(entry.id); setHomeConversationRevision((value) => value + 1); } else { adoptedProjectHydration.replaceReady(entry.snapshot); } setPortfolio(restoredPortfolio); setPortfolioError(''); setActiveWorkspace(type); } catch { let compensated = !staged; try { if (staged) { if (type === 'home') await rawHomeConversationRepositoryRef.current.save(previous ?? { messages: [], proposals: [], input: '' }); else if (previous) await adoptedProjectRepositoryRef.current.saveAdopted(previous); else await adoptedProjectRepositoryRef.current.clearAdopted?.(); compensated = true; } } catch { compensated = false; } setPortfolioError(compensated ? '再開できませんでした。アーカイブは保持されています。もう一度お試しください。' : '再開できませんでした。アーカイブは保持されていますが、元の作業内容を復元できませんでした。'); } }} currentPlan={subscription.plan} onOpenProfile={() => setProfileOpen(true)}>
        <div className="px-5 py-6 sm:py-8">{workspaceContent()}</div>
      </WorkspaceShell>
      {((profileHydration.phase === 'loading' && !profileDialogDismissed) || profileHydration.phase === 'error' || profileOpen) && <div className="kadode-dialog-backdrop fixed inset-0 z-10 grid grid-cols-[minmax(0,1fr)] place-items-end overflow-x-hidden p-3 sm:place-items-center sm:p-6" role="dialog" aria-modal="true" aria-label="あなたの情報">{profileHydration.phase === 'loading' ? <div className="kadode-dialog-panel w-full rounded-3xl p-6 shadow-xl sm:max-w-2xl">準備しています…</div> : profileHydration.phase === 'error' ? <ProfileLoadFailure onRetry={retryProfileLoad} /> : <UserProfileInterview initialProfile={profileHydration.value} repository={profileRepositoryRef.current} onClose={() => setProfileOpen(false)} onComplete={completeProfile} />}</div>}
    </main>
  );
}
