import { useEffect, useRef, useState } from 'react';
import './LocalHomeSurface.css';
import { safePublicCitationUrl } from '../runtime/publicCitationUrl.js';

const TABS = [
  { id: 'ideas', label: 'アイデア', icon: 'idea' },
  { id: 'assets', label: 'あなたのアセット', icon: 'asset' },
  { id: 'people', label: '人的ネットワーク', icon: 'people' },
];
const IDEA_SECTIONS = [
  'エグゼクティブサマリー', 'ビジネスモデル', '顧客とマーケットサイズ', '収益モデル',
  '競争優位性', '実現可能性', 'リスク・撤退ライン', 'リスクミニマムなロードマップ',
];
const researchStatusLabel = (status) => status === 'prior_research_sources_missing' ? '過去調査・現在の出典を表示できません' : status === 'prior_research_import' ? '過去調査を取り込みました' : status === 'research_sources_missing' ? '調査済み・出典を表示できません' : status === 'researched' ? '調査済み' : status === 'unresearched' ? '未調査' : '調査状態未確認';
const compactResearchStatusLabel = (status) => ['prior_research_sources_missing', 'prior_research_import', 'research_sources_missing', 'researched'].includes(status) ? '調査済み' : status === 'unresearched' ? '未調査' : null;

function HomeTabIcon({ name }) {
  const paths = {
    idea: <><path d="M9 18h6" /><path d="M10 22h4" /><path d="M8.5 14.5a7 7 0 1 1 7 0c-.9.7-1.5 1.7-1.5 2.5h-4c0-.8-.6-1.8-1.5-2.5Z" /><path d="M12 3v1" /></>,
    asset: <><rect x="3.5" y="4" width="17" height="16" rx="2" /><path d="M8 8h8" /><path d="M8 12h8" /><path d="M8 16h5" /></>,
    people: <><circle cx="12" cy="5" r="2.5" /><circle cx="5" cy="18" r="2.5" /><circle cx="19" cy="18" r="2.5" /><path d="m10.8 7.2-4.5 8.6M13.2 7.2l4.5 8.6M7.5 18h9" /></>,
  };
  return <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>;
}

function EditIcon() {
  return <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="m15 5 4 4" /><path d="M4 20h4l11-11a2.8 2.8 0 0 0-4-4L4 16v4Z" /></svg>;
}

function TrashIcon() {
  return <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M4 7h16" /><path d="M10 11v6M14 11v6" /><path d="m6 7 1 13h10l1-13" /><path d="M9 7V4h6v3" /></svg>;
}

function canArchiveRecord(kind, revision) {
  return Number.isSafeInteger(revision) && revision >= (kind === 'idea' ? 0 : 1);
}

export function LocalHomeSurface({ client, onOpenServices }) {
  const [tab, setTab] = useState('ideas');
  const [home, setHome] = useState({ status: 'loading', ideas: [], assets: [], profile: null });
  const [selectedId, setSelectedId] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const [assetDraft, setAssetDraft] = useState(null);
  const [assetSaving, setAssetSaving] = useState(false);
  const [assetNotice, setAssetNotice] = useState('');
  const [ideaDraft, setIdeaDraft] = useState(null);
  const [ideaSaving, setIdeaSaving] = useState(false);
  const [ideaNotice, setIdeaNotice] = useState('');
  const [deleteConfirmation, setDeleteConfirmation] = useState(null);
  const [deletePending, setDeletePending] = useState(false);
  const [deleteNotice, setDeleteNotice] = useState('');
  const [homeReloadNeeded, setHomeReloadNeeded] = useState(false);
  const homeHeadingRef = useRef(null);
  const deleteTriggerRef = useRef(null);
  const deleteConfirmRef = useRef(null);
  const deleteDialogRef = useRef(null);
  const deleteControllerRef = useRef(null);
  const hadDeleteDialog = useRef(false);

  useEffect(() => {
    deleteControllerRef.current?.abort();
    deleteControllerRef.current = null;
    setDeleteConfirmation(null);
    setDeletePending(false);
    setDeleteNotice('');
    setHomeReloadNeeded(false);
    const controller = new AbortController();
    setHome({ status: 'loading', ideas: [], assets: [], profile: null });
    Promise.resolve().then(() => client.getHome({ signal: controller.signal }))
      .then((result) => { if (!controller.signal.aborted) setHome(result); })
      .catch(() => { if (!controller.signal.aborted) setHome({ status: 'failed', ideas: [], assets: [], profile: null }); });
    return () => {
      controller.abort();
      deleteControllerRef.current?.abort();
    };
  }, [client, attempt]);

  useEffect(() => {
    if (!deleteConfirmation) {
      if (hadDeleteDialog.current) {
        if (deleteTriggerRef.current?.isConnected) deleteTriggerRef.current.focus();
        else homeHeadingRef.current?.focus();
      }
      hadDeleteDialog.current = false;
      return undefined;
    }
    hadDeleteDialog.current = true;
    if (deletePending) deleteDialogRef.current?.focus();
    else deleteConfirmRef.current?.focus();
    const closeOnEscape = (event) => {
      if (event.key === 'Escape' && !deletePending) setDeleteConfirmation(null);
      if (event.key === 'Tab') {
        const buttons = [...(deleteDialogRef.current?.querySelectorAll('button:not(:disabled)') ?? [])];
        if (!buttons.length) {
          event.preventDefault();
          deleteDialogRef.current?.focus();
        } else if (event.shiftKey && document.activeElement === buttons[0]) {
          event.preventDefault();
          buttons.at(-1).focus();
        } else if (!event.shiftKey && document.activeElement === buttons.at(-1)) {
          event.preventDefault();
          buttons[0].focus();
        }
      }
    };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [deleteConfirmation, deletePending]);

  const selectedIdea = home.ideas.find((idea) => idea.id === selectedId) ?? home.ideas[0] ?? null;
  function editIdea(idea) {
    setIdeaDraft({ id: idea.id, title: idea.title, description: idea.description ?? '', revision: idea.revision });
    setIdeaNotice('');
  }
  async function saveIdea(event) {
    event.preventDefault();
    if (!ideaDraft?.title.trim() || ideaSaving) return;
    setIdeaSaving(true);
    setIdeaNotice('');
    try {
      const saved = await client.saveIdea(ideaDraft.id, {
        title: ideaDraft.title,
        description: ideaDraft.description,
        expectedRevision: ideaDraft.revision,
      });
      const refreshed = await client.getHome();
      setHome(refreshed);
      setSelectedId(saved.id);
      setIdeaDraft(null);
      setIdeaNotice('変更を保存しました。');
    } catch (error) {
      setIdeaNotice(error?.kind === 'conflict' ? '別の更新がありました。最新内容を読み直してから編集してください。' : '保存できませんでした。入力内容は残っています。');
    } finally {
      setIdeaSaving(false);
    }
  }
  function editAsset(asset) {
    setAssetDraft({ id: asset.id, name: asset.name, description: asset.description, revision: asset.revision });
    setAssetNotice('');
  }
  async function saveAsset(event) {
    event.preventDefault();
    if (!assetDraft?.name.trim() || assetSaving) return;
    setAssetSaving(true);
    setAssetNotice('');
    try {
      await client.saveAsset(assetDraft.id, {
        name: assetDraft.name,
        description: assetDraft.description,
        expectedRevision: assetDraft.revision,
      });
      const refreshed = await client.getHome();
      setHome(refreshed);
      setAssetDraft(null);
      setAssetNotice('変更を保存しました。');
    } catch (error) {
      setAssetNotice(error?.kind === 'conflict' ? '別の更新がありました。最新内容を読み直してから編集してください。' : '保存できませんでした。入力内容は残っています。');
    } finally {
      setAssetSaving(false);
    }
  }

  async function refreshHome(signal) {
    const refreshed = await client.getHome({ signal });
    if (!signal.aborted) setHome(refreshed);
    return !signal.aborted;
  }

  async function archiveConfirmedRecord() {
    const record = deleteConfirmation;
    if (!record || deletePending || !canArchiveRecord(record.kind, record.revision)) return;
    const controller = new AbortController();
    deleteControllerRef.current = controller;
    setDeletePending(true);
    setDeleteNotice('');
    setHomeReloadNeeded(false);
    try {
      await client.archiveRecord(record.kind, record.id, record.revision, { signal: controller.signal });
      if (controller.signal.aborted) return;
      setHome((current) => {
        const ideas = record.kind === 'idea' ? current.ideas.filter((idea) => idea.id !== record.id) : current.ideas;
        const assets = record.kind === 'asset' ? current.assets.filter((asset) => asset.id !== record.id) : current.assets;
        return { ...current, status: ideas.length + assets.length ? 'ready' : 'empty', ideas, assets };
      });
      setDeleteConfirmation(null);
      try {
        await refreshHome(controller.signal);
        if (!controller.signal.aborted) setDeleteNotice(`${record.title}を削除しました。サービス管理の削除済み一覧から復元できます。`);
      } catch {
        if (!controller.signal.aborted) {
          setHomeReloadNeeded(true);
          setDeleteNotice(`${record.title}を削除しました。一覧を更新できませんでした。`);
        }
      }
    } catch (error) {
      if (controller.signal.aborted) return;
      if (error?.kind === 'conflict') {
        try {
          await refreshHome(controller.signal);
          if (!controller.signal.aborted) {
            setDeleteConfirmation(null);
            setDeleteNotice(`${record.title}は別の更新があったため削除できませんでした。最新の一覧を読み込みました。内容を確認してから操作してください。`);
          }
        } catch {
          if (!controller.signal.aborted) {
            setHomeReloadNeeded(true);
            setDeleteNotice('別の更新があり削除できませんでした。最新の一覧を読み込めません。');
          }
        }
      } else {
        setDeleteNotice('削除できませんでした。状態を確認して、もう一度お試しください。');
      }
    } finally {
      if (!controller.signal.aborted) {
        setDeletePending(false);
        deleteControllerRef.current = null;
      }
    }
  }
  return <main className="local-home" aria-labelledby="local-home-heading">
    <h1 ref={homeHeadingRef} id="local-home-heading" className="sr-only" tabIndex={-1}>ホーム</h1>
    <div role="tablist" aria-label="ホームの項目" className="local-home__tabs">
      {TABS.map(({ id, label, icon }) => <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => setTab(id)}><HomeTabIcon name={icon} /><span>{label}</span></button>)}
    </div>
    {home.status === 'loading' && <p role="status" className="local-home__notice">保存内容を読み込んでいます。</p>}
    {home.status === 'failed' && <div className="local-home__notice" role="alert">保存内容を読み込めませんでした。<button type="button" onClick={() => setAttempt((value) => value + 1)}>再試行</button></div>}
    {home.status === 'stopped' && <div className="local-home__notice" role="status">Dots.は停止中です。<button type="button" onClick={onOpenServices}>サービス管理を開く</button></div>}
    {['ready', 'empty'].includes(home.status) && tab === 'ideas' && <section className="local-home__idea-layout" aria-label="アイデア">
      <div className="local-home__idea-list">
        <h2 id="idea-list-heading" tabIndex={-1}>記録したアイデア <span>{home.ideas.length}件</span></h2>
        {home.ideas.length ? <div className="local-home__cards">{home.ideas.map((idea) => {
          const summary = idea.brief_sections?.[0]?.trim() || idea.summary;
          const isPriorResearch = idea.research_status?.startsWith('prior_research');
          const statusAnnouncement = `${researchStatusLabel(idea.research_status)}${isPriorResearch ? '（実行済み調査ではありません）' : ''}`;
          return <article key={idea.id} className="local-home__idea-card" data-selected={selectedIdea?.id === idea.id ? 'true' : 'false'}>
            <button type="button" className="local-home__idea-select" aria-pressed={selectedIdea?.id === idea.id} onClick={() => { setSelectedId(idea.id); setIdeaDraft(null); setIdeaNotice(''); }}>
              <span className="local-home__idea-heading"><strong title={idea.title}>{idea.title}</strong></span>
              {compactResearchStatusLabel(idea.research_status) && <span className="local-home__status-badge" data-research-state={idea.research_status} aria-label={statusAnnouncement}>{compactResearchStatusLabel(idea.research_status)}</span>}
              {summary && <span className="local-home__idea-summary">{summary}</span>}
            </button>
          </article>;
        })}</div> : <p className="local-home__notice">まだアイデアの記録はありません。ChatGPTで話したアイデアをDots.へ保存すると、ここに並びます。</p>}
      </div>
      {selectedIdea && <article className="local-home__idea-detail" aria-labelledby="selected-idea-heading">
        <div className="local-home__detail-header">
          <h2 id="selected-idea-heading">{selectedIdea.title}</h2>
          {!ideaDraft && <div className="local-home__card-actions">
            <button type="button" className="local-home__icon-button" aria-label={`編集: ${selectedIdea.title}`} title="題名と説明を編集" disabled={!canArchiveRecord('idea', selectedIdea.revision)} onClick={() => editIdea(selectedIdea)}><EditIcon /></button>
            <button type="button" className="local-home__icon-button" aria-label={`削除: ${selectedIdea.title}`} title={canArchiveRecord('idea', selectedIdea.revision) ? `「${selectedIdea.title}」を削除` : '最新の記録情報を読み込んでから削除できます'} disabled={!canArchiveRecord('idea', selectedIdea.revision) || deletePending} onClick={(event) => { deleteTriggerRef.current = event.currentTarget; setDeleteNotice(''); setDeleteConfirmation({ id: selectedIdea.id, kind: 'idea', title: selectedIdea.title, revision: selectedIdea.revision }); }}><TrashIcon /></button>
          </div>}
        </div>
        {ideaDraft?.id === selectedIdea.id ? <form onSubmit={saveIdea} className="local-home__edit-form local-home__idea-edit-form">
          <p>題名だけの変更は調査結果を引き継ぎます。説明を変えると以前の調査は履歴に残り、この案の現行調査からは外れます。</p>
          <label htmlFor="idea-edit-title">題名</label>
          <textarea id="idea-edit-title" rows={1} maxLength={200} required value={ideaDraft.title} onChange={(event) => setIdeaDraft((current) => ({ ...current, title: event.target.value }))} />
          <label htmlFor="idea-edit-description">説明</label>
          <textarea id="idea-edit-description" rows={6} maxLength={4000} value={ideaDraft.description} onChange={(event) => setIdeaDraft((current) => ({ ...current, description: event.target.value }))} />
          {ideaNotice && <p role="alert">{ideaNotice}</p>}
          <div><button type="submit" disabled={!ideaDraft.title.trim() || ideaSaving}>{ideaSaving ? '保存中…' : '保存する'}</button><button type="button" disabled={ideaSaving} onClick={() => { setIdeaDraft(null); setIdeaNotice(''); }}>キャンセル</button></div>
        </form> : <>
          <p className="local-home__research-status">{researchStatusLabel(selectedIdea.research_status)}</p>
          {selectedIdea.research_status !== 'researched' && selectedIdea.description && <p className="local-home__idea-description">{selectedIdea.description}</p>}
        </>}
        {ideaNotice && !ideaDraft && <p role="status">{ideaNotice}</p>}
        <div className="local-home__section-list">{IDEA_SECTIONS.map((heading, index) => {
          const saved = selectedIdea.brief_sections?.[index]?.trim();
          const content = saved || (index === 0 ? selectedIdea.summary : '') || '未整理';
          const citations = Array.isArray(selectedIdea.brief_citations?.[index])
            ? selectedIdea.brief_citations[index].filter((citation) => citation && typeof citation.title === 'string' && citation.title.trim() && safePublicCitationUrl(citation.url))
            : [];
          return <section key={heading}>
            <h3>{heading}</h3>
            <p className={content === '未整理' ? 'local-home__unwritten' : ''}>{content}</p>
            {citations.length > 0 && <p className="local-home__citation">出典: {citations.map((citation, citationIndex) => <span key={`${citation.source_id ?? citation.evidence_id ?? citation.url}-${citationIndex}`}>
              {citationIndex > 0 ? '、' : ''}<a href={safePublicCitationUrl(citation.url)} target="_blank" rel="noopener noreferrer">{citation.title.trim()}</a>
            </span>)}</p>}
          </section>;
        })}</div>
      </article>}
    </section>}
    {['ready', 'empty'].includes(home.status) && tab === 'assets' && <section className="local-home__asset-layout" aria-label="あなたのアセット">
      <div className="local-home__asset-list">
        <h2>アセット一覧 <span>{home.assets.length}件</span></h2>
        {home.assets.length ? <div className="local-home__cards">{home.assets.map((asset) => <article key={asset.id} className="local-home__asset-card">
          {assetDraft?.id === asset.id ? <form onSubmit={saveAsset} className="local-home__edit-form">
            <label htmlFor={`asset-title-${asset.id}`}>題名</label>
            <textarea id={`asset-title-${asset.id}`} name="title" rows={1} maxLength={200} required value={assetDraft.name} onChange={(event) => setAssetDraft((current) => ({ ...current, name: event.target.value }))} />
            <label htmlFor={`asset-content-${asset.id}`}>内容</label>
            <textarea id={`asset-content-${asset.id}`} name="content" rows={8} maxLength={4000} value={assetDraft.description} onChange={(event) => setAssetDraft((current) => ({ ...current, description: event.target.value }))} />
            {assetNotice && <p role="alert">{assetNotice}</p>}
            <div><button type="submit" disabled={!assetDraft.name.trim() || assetSaving}>{assetSaving ? '保存中…' : '保存する'}</button><button type="button" aria-label="キャンセル" disabled={assetSaving} onClick={() => { setAssetDraft(null); setAssetNotice(''); }}>キャンセル</button></div>
          </form> : <>
            <h3>{asset.name}</h3>
            {asset.description ? <p>{asset.description}</p> : <p className="local-home__unwritten">内容はありません</p>}
            <div className="local-home__card-actions">
              <button type="button" className="local-home__icon-button" aria-label={`編集: ${asset.name}`} disabled={!Number.isSafeInteger(asset.revision) || asset.revision < 1} onClick={() => editAsset(asset)}><EditIcon /></button>
              <button type="button" className="local-home__icon-button" aria-label={`削除: ${asset.name}`} title={canArchiveRecord('asset', asset.revision) ? `「${asset.name}」を削除` : '最新の記録情報を読み込んでから削除できます'} disabled={!canArchiveRecord('asset', asset.revision) || deletePending} onClick={(event) => { event.stopPropagation(); deleteTriggerRef.current = event.currentTarget; setDeleteNotice(''); setDeleteConfirmation({ id: asset.id, kind: 'asset', title: asset.name, revision: asset.revision }); }}><TrashIcon /></button>
            </div>
          </>}
        </article>)}</div> : <p className="local-home__notice">記録はまだありません。</p>}
        {assetNotice && !assetDraft && <p role="status">{assetNotice}</p>}
      </div>
    </section>}
    {deleteNotice && <p role="status" aria-live="polite" className="local-home__delete-notice">{deleteNotice}{homeReloadNeeded && <button type="button" onClick={() => { setDeleteNotice(''); setHomeReloadNeeded(false); setAttempt((value) => value + 1); }}>ホームを再読み込み</button>}</p>}
    {deleteConfirmation && <div className="local-home__delete-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !deletePending) setDeleteConfirmation(null); }}>
      <section ref={deleteDialogRef} role="alertdialog" aria-modal="true" aria-labelledby="local-delete-heading" aria-describedby="local-delete-description" tabIndex={-1} className="local-home__delete-dialog">
        <h2 id="local-delete-heading">「{deleteConfirmation.title}」を削除しますか？</h2>
        <p id="local-delete-description">通常の一覧から非表示にします。サービス管理の削除済み一覧から復元できます。履歴と根拠は保持されます。</p>
        {deleteNotice && <p role="alert" className="local-home__delete-error">{deleteNotice}</p>}
        <div>
          <button type="button" disabled={deletePending} onClick={() => { setDeleteConfirmation(null); setDeleteNotice(''); }}>キャンセル</button>
          <button ref={deleteConfirmRef} type="button" disabled={deletePending} onClick={() => { void archiveConfirmedRecord(); }}>{deletePending ? '削除中…' : '削除する'}</button>
        </div>
      </section>
    </div>}
    {tab === 'people' && <section className="local-home__notice" role="tabpanel"><h2>人的ネットワーク</h2><p>今後実装予定</p></section>}
  </main>;
}

export default LocalHomeSurface;
