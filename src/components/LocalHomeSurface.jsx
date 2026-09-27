import { useEffect, useState } from 'react';
import './LocalHomeSurface.css';

const TABS = [
  { id: 'ideas', label: 'アイデア' },
  { id: 'assets', label: 'あなたのアセット' },
  { id: 'people', label: '人的ネットワーク' },
];
const IDEA_SECTIONS = [
  'エグゼクティブサマリー', 'ビジネスモデル', '顧客とマーケットサイズ', '収益モデル',
  '競争優位性', '実現可能性', 'リスク・撤退ライン', 'リスクミニマムなロードマップ',
];
const researchStatusLabel = (status) => status === 'researched' ? '調査済み' : status === 'unresearched' ? '未調査' : '調査状態未確認';

export function LocalHomeSurface({ client, onOpenServices }) {
  const [tab, setTab] = useState('ideas');
  const [home, setHome] = useState({ status: 'loading', ideas: [], assets: [], profile: null });
  const [selectedId, setSelectedId] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const [editingSelf, setEditingSelf] = useState(false);
  const [selfDraft, setSelfDraft] = useState('');
  const [selfSaving, setSelfSaving] = useState(false);
  const [selfNotice, setSelfNotice] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    setHome({ status: 'loading', ideas: [], assets: [], profile: null });
    Promise.resolve().then(() => client.getHome({ signal: controller.signal }))
      .then((result) => { if (!controller.signal.aborted) setHome(result); })
      .catch(() => { if (!controller.signal.aborted) setHome({ status: 'failed', ideas: [], assets: [], profile: null }); });
    return () => controller.abort();
  }, [client, attempt]);

  const selectedIdea = home.ideas.find((idea) => idea.id === selectedId) ?? home.ideas[0] ?? null;
  const selfIntroduction = home.assets.find((asset) => asset.name === '自己紹介') ?? null;
  async function saveSelf(event) {
    event.preventDefault();
    if (!selfDraft.trim() || selfSaving) return;
    setSelfSaving(true);
    setSelfNotice('');
    try {
      await client.saveSelfIntroduction(selfDraft, selfIntroduction?.id ?? null);
      const refreshed = await client.getHome();
      setHome(refreshed);
      setEditingSelf(false);
      setSelfNotice('自己紹介を保存しました。');
    } catch (error) {
      setSelfNotice(error?.kind === 'conflict' ? '別の更新がありました。ページを読み直してから編集してください。' : '保存できませんでした。内容は入力欄に残っています。');
    } finally {
      setSelfSaving(false);
    }
  }
  return <main className="local-home" aria-labelledby="local-home-heading">
    <h1 id="local-home-heading" className="sr-only">ホーム</h1>
    <div role="tablist" aria-label="ホームの項目" className="local-home__tabs">
      {TABS.map(({ id, label }) => <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => setTab(id)}>{label}</button>)}
    </div>
    {home.status === 'loading' && <p role="status" className="local-home__notice">保存内容を読み込んでいます。</p>}
    {home.status === 'failed' && <div className="local-home__notice" role="alert">保存内容を読み込めませんでした。<button type="button" onClick={() => setAttempt((value) => value + 1)}>再試行</button></div>}
    {home.status === 'stopped' && <div className="local-home__notice" role="status">Dots.は停止中です。<button type="button" onClick={onOpenServices}>サービス管理を開く</button></div>}
    {['ready', 'empty'].includes(home.status) && tab === 'ideas' && <section className="local-home__idea-layout" aria-label="アイデア">
      <div className="local-home__idea-list">
        <h2>記録したアイデア <span>{home.ideas.length}件</span></h2>
        {home.ideas.length ? <div className="local-home__cards">{home.ideas.map((idea) => {
          const summary = idea.brief_sections?.[0]?.trim() || idea.summary;
          return <button key={idea.id} type="button" className="local-home__idea-card" aria-pressed={selectedIdea?.id === idea.id} onClick={() => setSelectedId(idea.id)}><strong>{idea.title}</strong><span>{researchStatusLabel(idea.research_status)}</span>{summary && <span>{summary}</span>}</button>;
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
          return <section key={heading}><h3>{index}. {heading}</h3><p className={content === '未整理' ? 'local-home__unwritten' : ''}>{content}</p></section>;
        })}</div>
      </article>}
    </section>}
    {['ready', 'empty'].includes(home.status) && tab === 'assets' && <section className="local-home__asset-layout" aria-label="あなたのアセット">
      <article className="local-home__panel"><p className="local-home__eyebrow">ABOUT YOU</p><h2>あなたについて</h2>{home.profile?.displayName && <p className="local-home__profile-name">{home.profile.displayName}</p>}
        {!editingSelf && <><p>{selfIntroduction?.description || '自己紹介はまだ成文化されていません。ChatGPTとの壁打ちから記録できます。'}</p><button type="button" className="local-home__edit" onClick={() => { setSelfDraft(selfIntroduction?.description ?? ''); setSelfNotice(''); setEditingSelf(true); }}>この画面で編集</button></>}
        {editingSelf && <form onSubmit={saveSelf} className="local-home__edit-form"><label htmlFor="self-intro-edit">自己紹介</label><textarea id="self-intro-edit" value={selfDraft} maxLength={4000} rows={8} onChange={(event) => setSelfDraft(event.target.value)} /><div><button type="submit" disabled={!selfDraft.trim() || selfSaving}>{selfSaving ? '保存中…' : '保存する'}</button><button type="button" disabled={selfSaving} onClick={() => setEditingSelf(false)}>キャンセル</button></div></form>}
        {selfNotice && <p role="status">{selfNotice}</p>}
        <p className="local-home__guidance">基本はChatGPTで壁打ちし、整理された内容をDots.へ記録します。この画面で保存した補足は、初期設定ではChatGPTに渡しません。</p>
      </article>
      <section className="local-home__panel"><h2>保有している資産</h2>{home.assets.length ? <ul>{home.assets.map((asset) => <li key={asset.id}><strong>{asset.name}</strong>{asset.description && <p>{asset.description}</p>}</li>)}</ul> : <p>まだ資産の記録はありません。</p>}</section>
    </section>}
    {tab === 'people' && <section className="local-home__notice" role="tabpanel"><h2>人的ネットワーク</h2><p>今後実装予定</p></section>}
  </main>;
}

export default LocalHomeSurface;
