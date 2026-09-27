import { useEffect, useState } from 'react';
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
const compactResearchStatusLabel = (status) => status === 'prior_research_sources_missing' || status === 'prior_research_import' ? '過去調査あり' : status === 'research_sources_missing' ? '調査済み・出典未表示' : status === 'researched' ? '調査済み' : status === 'unresearched' ? '未調査' : '状態未確認';

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

export function LocalHomeSurface({ client, onOpenServices }) {
  const [tab, setTab] = useState('ideas');
  const [home, setHome] = useState({ status: 'loading', ideas: [], assets: [], profile: null });
  const [selectedId, setSelectedId] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const [assetDraft, setAssetDraft] = useState(null);
  const [assetSaving, setAssetSaving] = useState(false);
  const [assetNotice, setAssetNotice] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    setHome({ status: 'loading', ideas: [], assets: [], profile: null });
    Promise.resolve().then(() => client.getHome({ signal: controller.signal }))
      .then((result) => { if (!controller.signal.aborted) setHome(result); })
      .catch(() => { if (!controller.signal.aborted) setHome({ status: 'failed', ideas: [], assets: [], profile: null }); });
    return () => controller.abort();
  }, [client, attempt]);

  const selectedIdea = home.ideas.find((idea) => idea.id === selectedId) ?? home.ideas[0] ?? null;
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
  return <main className="local-home" aria-labelledby="local-home-heading">
    <h1 id="local-home-heading" className="sr-only">ホーム</h1>
    <div role="tablist" aria-label="ホームの項目" className="local-home__tabs">
      {TABS.map(({ id, label, icon }) => <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => setTab(id)}><HomeTabIcon name={icon} /><span>{label}</span></button>)}
    </div>
    {home.status === 'loading' && <p role="status" className="local-home__notice">保存内容を読み込んでいます。</p>}
    {home.status === 'failed' && <div className="local-home__notice" role="alert">保存内容を読み込めませんでした。<button type="button" onClick={() => setAttempt((value) => value + 1)}>再試行</button></div>}
    {home.status === 'stopped' && <div className="local-home__notice" role="status">Dots.は停止中です。<button type="button" onClick={onOpenServices}>サービス管理を開く</button></div>}
    {['ready', 'empty'].includes(home.status) && tab === 'ideas' && <section className="local-home__idea-layout" aria-label="アイデア">
      <div className="local-home__idea-list">
        <h2>記録したアイデア <span>{home.ideas.length}件</span></h2>
        {home.ideas.length ? <div className="local-home__cards">{home.ideas.map((idea) => {
          const summary = idea.brief_sections?.[0]?.trim() || idea.summary;
          const isPriorResearch = idea.research_status?.startsWith('prior_research');
          const statusAnnouncement = `${researchStatusLabel(idea.research_status)}${isPriorResearch ? '（実行済み調査ではありません）' : ''}`;
          return <button key={idea.id} type="button" className="local-home__idea-card" aria-pressed={selectedIdea?.id === idea.id} onClick={() => setSelectedId(idea.id)}><span className="local-home__idea-heading"><strong title={idea.title}>{idea.title}</strong><span className="local-home__status-badge" data-research-state={idea.research_status ?? 'unknown'} aria-label={statusAnnouncement}>{compactResearchStatusLabel(idea.research_status)}</span></span>{summary && <span className="local-home__idea-summary">{summary}</span>}</button>;
        })}</div> : <p className="local-home__notice">まだアイデアの記録はありません。ChatGPTで話したアイデアをDots.へ保存すると、ここに並びます。</p>}
      </div>
      {selectedIdea && <article className="local-home__idea-detail" aria-labelledby="selected-idea-heading">
        <p className="local-home__eyebrow">IDEA</p>
        <h2 id="selected-idea-heading">{selectedIdea.title}</h2>
        <p>{researchStatusLabel(selectedIdea.research_status)}</p>
        {selectedIdea.research_status !== 'researched' && selectedIdea.description && <p className="local-home__idea-description">{selectedIdea.description}</p>}
        <div className="local-home__section-list">{IDEA_SECTIONS.map((heading, index) => {
          const saved = selectedIdea.brief_sections?.[index]?.trim();
          const content = saved || (index === 0 ? selectedIdea.summary : '') || '未整理';
          const citations = Array.isArray(selectedIdea.brief_citations?.[index])
            ? selectedIdea.brief_citations[index].filter((citation) => citation && typeof citation.title === 'string' && citation.title.trim() && safePublicCitationUrl(citation.url))
            : [];
          return <section key={heading}>
            <h3>{index}. {heading}</h3>
            <p className={content === '未整理' ? 'local-home__unwritten' : ''}>{content}</p>
            {citations.length > 0 && <p className="local-home__citation">出典: {citations.map((citation, citationIndex) => <span key={`${citation.source_id ?? citation.evidence_id ?? citation.url}-${citationIndex}`}>
              {citationIndex > 0 ? '、' : ''}<a href={safePublicCitationUrl(citation.url)} target="_blank" rel="noopener noreferrer">{citation.title.trim()}</a>
            </span>)}</p>}
          </section>;
        })}</div>
      </article>}
    </section>}
    {['ready', 'empty'].includes(home.status) && tab === 'assets' && <section className="local-home__asset-layout" aria-label="あなたのアセット">
      <section className="local-home__panel" style={{ gridColumn: '1 / -1' }}>
        <h2>アセット一覧 <span>{home.assets.length}件</span></h2>
        {home.assets.length ? <div className="local-home__cards">{home.assets.map((asset) => <article key={asset.id} className="local-home__asset-card local-home__panel">
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
            <button type="button" className="local-home__icon-button" aria-label={`編集: ${asset.name}`} disabled={!Number.isSafeInteger(asset.revision) || asset.revision < 1} onClick={() => editAsset(asset)}><EditIcon /></button>
          </>}
        </article>)}</div> : <p className="local-home__notice">記録はまだありません。</p>}
        {assetNotice && !assetDraft && <p role="status">{assetNotice}</p>}
      </section>
    </section>}
    {tab === 'people' && <section className="local-home__notice" role="tabpanel"><h2>人的ネットワーク</h2><p>今後実装予定</p></section>}
  </main>;
}

export default LocalHomeSurface;
