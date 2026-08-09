import { useEffect, useRef, useState } from 'react';

import { AI_COPY_CATALOG } from '../copy/aiVoice';

const EMPTY_CONVERSATIONS = { space: [], project: [] };

export function createBrowserChatRepository(storage = globalThis.localStorage) {
  const key = 'kadode:workspace-chat';
  return {
    load: async () => JSON.parse(storage?.getItem(key) || '{"draft":"","conversations":{}}'),
    save: async (next) => { storage?.setItem(key, JSON.stringify(next)); return next; },
  };
}

function replyFor(message, scope) {
  const subject = message.trim() || 'その考え';
  return scope === 'space'
    ? `「${subject}」をspace全体の経験・資料・過去の判断と照らして整理します。${AI_COPY_CATALOG.inference.body}`
    : `「${subject}」をこのプロジェクトの仮説として整理します。${AI_COPY_CATALOG.nextStep.body}`;
}

function availableKnowledge(knowledge) {
  return knowledge.filter((item) => item.status !== 'unavailable' && item.state !== 'deleted');
}

export function WorkspaceChatPage({ repository, currentPage = '事業のタネ', profileReady = false, knowledge = [] }) {
  const repositoryRef = useRef(null);
  if (!repositoryRef.current) repositoryRef.current = repository ?? createBrowserChatRepository();
  const [scope, setScope] = useState('space');
  const [conversations, setConversations] = useState(EMPTY_CONVERSATIONS);
  const [draft, setDraft] = useState('');
  const [hydrated, setHydrated] = useState(false);
  const [candidateState, setCandidateState] = useState('');
  const [rejectionReason, setRejectionReason] = useState('');
  const [decisions, setDecisions] = useState({});
  const [error, setError] = useState('');
  const draftChanged = useRef(false);
  const visibleKnowledge = availableKnowledge(knowledge);
  const messages = conversations[scope] ?? [];

  useEffect(() => {
    let active = true;
    repositoryRef.current.load().then((saved) => {
      if (!active) return;
      setConversations({ ...EMPTY_CONVERSATIONS, ...(saved?.conversations ?? {}) });
      setDecisions(saved?.decisions ?? {});
      if (!draftChanged.current) setDraft(saved?.draft ?? '');
      setHydrated(true);
    }).catch(() => { setError('会話を読み込めませんでした。入力は端末内に保存されません。'); setHydrated(true); });
    return () => { active = false; };
  }, []);

  function persist(nextConversations, nextDraft, nextDecisions = decisions) {
    repositoryRef.current.save({ conversations: nextConversations, draft: nextDraft, decisions: nextDecisions }).catch(() => setError('端末内への保存に失敗しました。'));
  }

  function send(event) {
    event.preventDefault();
    const content = draft.trim();
    if (!content) return;
    const nextMessages = [...messages, { role: 'user', content }, { role: 'assistant', content: replyFor(content, scope) }];
    const nextConversations = { ...conversations, [scope]: nextMessages };
    setConversations(nextConversations);
    setDraft('');
    setCandidateState(decisions[scope]?.status === 'rejected' ? '' : 'presented');
    persist(nextConversations, '');
  }

  function decide(status) {
    const nextDecisions = { ...decisions, [scope]: { status, reason: status === 'rejected' ? rejectionReason.trim() : '' } };
    setDecisions(nextDecisions);
    setCandidateState(status);
    persist(conversations, draft, nextDecisions);
  }

  function chooseScope(nextScope) {
    setScope(nextScope);
    setCandidateState('');
    setRejectionReason('');
  }

  return <section className="mx-auto flex w-full max-w-5xl flex-col gap-5" aria-labelledby="chat-heading">
    <header className="border-b border-stone-200 pb-5"><p className="text-xs font-bold tracking-[0.16em] text-emerald-700">LOCAL AI</p><h1 id="chat-heading" className="mt-2 text-3xl font-bold tracking-tight">AIチャット</h1><p className="mt-2 max-w-2xl text-sm leading-6 text-stone-600">外部サービスには送信しない、端末内のdeterministic previewです。</p></header>
    <div className="flex flex-wrap gap-2" aria-label="会話の種類"><button type="button" aria-pressed={scope === 'space'} onClick={() => chooseScope('space')} className="min-h-11 rounded-full border border-stone-300 px-4 text-sm font-bold aria-[pressed=true]:border-emerald-800 aria-[pressed=true]:bg-emerald-800 aria-[pressed=true]:text-white">portfolio steward</button><button type="button" aria-pressed={scope === 'project'} onClick={() => chooseScope('project')} className="min-h-11 rounded-full border border-stone-300 px-4 text-sm font-bold aria-[pressed=true]:border-emerald-800 aria-[pressed=true]:bg-emerald-800 aria-[pressed=true]:text-white">プロジェクト会話</button></div>
    <section className="rounded-2xl border border-stone-200 bg-stone-50 p-4" aria-labelledby="context-heading"><h2 id="context-heading" className="font-bold">会話に使う文脈</h2><ul className="mt-2 grid gap-1 text-sm text-stone-700"><li>現在ページ: {currentPage}</li><li>あなたの情報: {profileReady ? '確認済み' : '未確認'}</li><li>会話の範囲: {scope === 'space' ? 'user space全体' : 'プロジェクト単位の会話'}</li>{visibleKnowledge.map((item) => <li key={item.id}>{item.kind}: {item.sourceId} · {item.locator}</li>)}</ul></section>
    <div className="min-h-40 rounded-2xl border border-stone-200 bg-white p-4" aria-live="polite"><p className="text-sm font-bold text-stone-600">{hydrated ? '会話を再開できます' : '会話を読み込んでいます'}</p>{error && <p role="alert" className="mt-2 text-sm font-bold text-red-700">{error}</p>}{messages.length === 0 ? <p className="mt-4 text-sm text-stone-600">{scope === 'space' ? 'space全体について、今考えていることを書いてください。' : 'このプロジェクトで確かめたいことを書いてください。'}</p> : <ol className="mt-4 grid gap-3">{messages.map((message, index) => <li key={`${message.role}-${index}`} className={message.role === 'assistant' ? 'rounded-xl bg-stone-100 p-3 text-sm leading-6' : 'rounded-xl bg-emerald-50 p-3 text-sm leading-6'}><strong>{message.role === 'assistant' ? 'AI' : 'あなた'}</strong><p>{message.content}</p></li>)}</ol>}</div>
    {candidateState && <section className="rounded-2xl border border-rose-200 bg-rose-50 p-4" aria-labelledby="candidate-heading">
      <p className="text-xs font-bold tracking-[0.16em] text-rose-800">事業の芽 preview</p><h2 id="candidate-heading" className="mt-1 font-bold">会話から見つけた、深掘りできる候補</h2>
      {candidateState === 'adopted' && <p className="mt-2 text-sm">プロジェクトとして採用しました。次の会話で仮説を深掘りできます。</p>}
      {candidateState === 'deferred' && <p className="mt-2 text-sm">保留として残しました。プロジェクトは作成していません。</p>}
      {candidateState === 'rejected' && <p className="mt-2 text-sm">却下理由を記録しました。前提が変わるまで同じ候補は再提示しません。</p>}
      {candidateState === 'presented' && <><p className="mt-2 text-sm">判断は今ここで決めなくて構いません。採用だけがプロジェクトを作成します。</p><div className="mt-3 flex flex-wrap gap-2"><button type="button" onClick={() => decide('adopted')} className="min-h-11 rounded-full bg-emerald-800 px-4 text-sm font-bold text-white">プロジェクトに採用して深掘り</button><button type="button" onClick={() => decide('deferred')} className="min-h-11 rounded-full border border-stone-300 px-4 text-sm font-bold">保留</button></div><label className="mt-3 block text-sm font-bold">理由を添えて却下<textarea value={rejectionReason} onChange={(event) => setRejectionReason(event.target.value)} className="mt-1 min-h-20 w-full rounded-xl border border-stone-300 p-3 font-normal" /></label><button type="button" disabled={!rejectionReason.trim()} onClick={() => decide('rejected')} className="mt-2 min-h-11 rounded-full border border-stone-300 px-4 text-sm font-bold disabled:opacity-50">却下を記録</button></>}
    </section>}
    <form onSubmit={send} className="rounded-2xl border border-stone-300 bg-white p-3"><label htmlFor="workspace-chat-input" className="sr-only">AIへのメッセージ</label><textarea id="workspace-chat-input" value={draft} onChange={(event) => { draftChanged.current = true; setDraft(event.target.value); }} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} placeholder="考えていることを入力" className="min-h-24 w-full resize-y p-2 text-base leading-6 outline-none" /><div className="flex items-center justify-between gap-3 border-t border-stone-100 pt-3"><span className="text-xs text-stone-500">Enterで送信、Shift+Enterで改行</span><button type="submit" className="min-h-11 rounded-full bg-emerald-800 px-5 text-sm font-bold text-white">送信</button></div></form>
  </section>;
}
