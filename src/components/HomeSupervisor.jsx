import { useEffect, useMemo, useState } from 'react';

import { createLocalContextSnapshot } from '../context/contextSnapshot';

const storageKey = 'kadode:home-conversation';
const initialSnapshot = createLocalContextSnapshot({ ownerId: 'local-owner', surface: { name: 'Home', route: '/home' } });
const emptyState = { messages: [], proposals: [], input: '' };

export function createHomeConversationRepository(storage = globalThis.localStorage) {
  return {
    load: async () => {
      try {
        const value = JSON.parse(storage?.getItem(storageKey) || 'null');
        return value && Array.isArray(value.messages) && Array.isArray(value.proposals) ? { ...emptyState, ...value } : emptyState;
      } catch { return emptyState; }
    },
    save: async (value) => { storage?.setItem(storageKey, JSON.stringify(value)); return value; },
  };
}

export function proposeHomeAction(input, snapshot = initialSnapshot) {
  const action = /プロジェクト.*(一覧|確認)|一覧.*確認/.test(input) ? 'inspect_projects' : 'ideate';
  return {
    id: crypto.randomUUID(),
    fact: `現在のsurface: ${snapshot.surface.name}`,
    inference: `入力を「${action}」として整理しました。`,
    action,
    confirmed: false,
    status: 'pending',
  };
}

function nextQuestion(messages) {
  const text = messages.filter(({ role }) => role === 'user').map(({ content }) => content).join(' ');
  if (!/(誰|向け|担当|利用者|顧客)/.test(text)) return '誰の、どの場面での困りごとかを教えてください。';
  if (!/(困|手間|時間|不安|できない|探せない|負担)/.test(text)) return 'その人が今困っていることと、失われている時間を教えてください。';
  return '整理できました。右の提案を採用、保留、または理由付きで却下できます。';
}

export function HomeSupervisor({ repository, snapshot = initialSnapshot, onProjectAdopt, modelKey }) {
  const [browserRepository] = useState(() => createHomeConversationRepository());
  const activeRepository = repository ?? browserRepository;
  const [state, setState] = useState(emptyState);
  const [input, setInput] = useState('');
  const [rejectReason, setRejectReason] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    activeRepository.load().then((value) => {
      setState(value); setInput(value.input || '');
      const adopted = value.proposals.find(({ status }) => status === 'adopted');
      if (adopted) onProjectAdopt?.(adopted);
    }).catch(() => setError('会話を読み込めませんでした。'));
  }, [activeRepository, onProjectAdopt]);

  const messages = useMemo(() => state.messages, [state.messages]);
  async function persist(next) { await activeRepository.save(next); setState(next); }
  async function updateInput(value) {
    setInput(value);
    try { await activeRepository.save({ ...state, input: value }); } catch { setError('下書きを保存できませんでした。'); }
  }
  async function send(event) {
    event?.preventDefault();
    const content = input.trim();
    if (!content) { setError('発言を入力してください。'); return; }
    const user = { role: 'user', content };
    const nextMessages = [...messages, user];
    const proposal = proposeHomeAction(content, snapshot);
    const next = { messages: [...nextMessages, { role: 'assistant', content: nextQuestion(nextMessages) }], proposals: [proposal, ...state.proposals], input: '' };
    try { await persist(next); setInput(''); setError(''); } catch { setError('会話を保存できませんでした。再試行してください。'); }
  }
  async function decide(id, status) {
    if (status === 'rejected' && !rejectReason.trim()) { setError('却下理由を入力してください。'); return; }
    const proposals = state.proposals.map((proposal) => proposal.id === id ? { ...proposal, status, confirmed: status === 'adopted', ...(status === 'rejected' ? { rejectionReason: rejectReason.trim() } : {}) } : proposal);
    try {
      await persist({ ...state, proposals }); setRejectReason(''); setError('');
      if (status === 'adopted') onProjectAdopt?.(proposals.find((proposal) => proposal.id === id));
    } catch { setError('判断を保存できませんでした。再試行してください。'); }
  }

  return <section aria-labelledby="home-supervisor-heading" className="grid max-w-6xl gap-5 lg:grid-cols-[minmax(0,1.25fr)_minmax(20rem,0.75fr)]">
    <div className="rounded-3xl border border-stone-200 bg-white p-5 shadow-sm sm:p-6">
      <p className="text-xs font-bold uppercase tracking-[0.16em] text-stone-500">Home · {modelKey || 'local assistant'}</p>
      <h1 id="home-supervisor-heading" className="mt-2 text-2xl font-semibold tracking-tight">Kadode AI</h1>
      <p className="mt-2 text-sm leading-6 text-stone-600">アイデアを会話でほどき、判断する前に提案として確認します。</p>
      <ol className="mt-5 grid max-h-[26rem] gap-3 overflow-y-auto" aria-label="会話履歴">
        {messages.length === 0 && <li className="rounded-2xl bg-stone-50 p-4 text-sm text-stone-600">誰のどんな困りごとを解決したいか、自由に話してください。</li>}
        {messages.map((message, index) => <li key={`${message.role}-${index}`} className={`rounded-2xl p-4 text-sm leading-6 ${message.role === 'user' ? 'ml-8 bg-emerald-100' : 'mr-8 bg-stone-100'}`}><strong>{message.role === 'user' ? 'あなた' : 'Kadode'}</strong><p>{message.content}</p></li>)}
      </ol>
      <form onSubmit={send} className="mt-5 rounded-2xl border border-stone-300 p-3">
        <label htmlFor="home-supervisor-message" className="sr-only">Kadode AIへのメッセージ</label>
        <textarea id="home-supervisor-message" value={input} onChange={(event) => { void updateInput(event.target.value); }} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void send(); } }} rows={3} maxLength={1000} className="w-full resize-y p-2 text-base leading-6 outline-none" placeholder="例：工場の保全担当者が故障履歴を探せない" />
        <div className="mt-2 flex items-center justify-between gap-3"><p className="text-xs text-stone-500">Enterで送信、Shift+Enterで改行</p><button className="min-h-11 rounded-full bg-stone-900 px-5 py-2 text-sm font-bold text-white">発言を送信</button></div>
      </form>
    </div>
    <aside className="rounded-3xl border border-stone-200 bg-white p-5 shadow-sm sm:p-6" aria-label="提案と判断">
      <h2 className="text-lg font-semibold tracking-tight">提案</h2><p className="mt-1 text-sm text-stone-600">採用はProjectへ昇格します。</p>
      <div className="mt-4 grid gap-3">{state.proposals.length === 0 && <p className="rounded-2xl bg-stone-50 p-4 text-sm text-stone-600">会話から提案を作成します。</p>}{state.proposals.map((proposal) => <article key={proposal.id} className="rounded-2xl border border-stone-200 p-4"><p className="text-sm"><strong>事実:</strong> {proposal.fact}</p><p className="mt-2 text-sm"><strong>推論:</strong> {proposal.inference}</p><p className="mt-2 text-sm"><strong>操作:</strong> {proposal.action}</p>{proposal.status === 'adopted' ? <p role="status" className="mt-3 text-sm font-bold text-emerald-800">Projectへ採用済み</p> : proposal.status === 'held' ? <p role="status" className="mt-3 text-sm font-bold">保留中</p> : proposal.status === 'rejected' ? <p role="status" className="mt-3 text-sm text-red-800">却下: {proposal.rejectionReason}</p> : <><label className="mt-3 block text-sm" htmlFor={`reject-${proposal.id}`}>却下理由（却下時は必須）</label><textarea id={`reject-${proposal.id}`} value={rejectReason} onChange={(event) => setRejectReason(event.target.value)} rows={2} className="mt-1 w-full rounded-xl border border-stone-300 p-2 text-sm" /><div className="mt-3 flex flex-wrap gap-2"><button type="button" onClick={() => void decide(proposal.id, 'adopted')} className="min-h-11 rounded-full bg-stone-900 px-4 py-2 text-sm font-bold text-white">プロジェクトに採用</button><button type="button" onClick={() => void decide(proposal.id, 'held')} className="min-h-11 rounded-full border px-4 py-2 text-sm font-bold">保留</button><button type="button" onClick={() => void decide(proposal.id, 'rejected')} className="min-h-11 rounded-full border border-red-700 px-4 py-2 text-sm font-bold text-red-800">理由付きで却下</button></div></>}</article>)}</div>
    </aside>
    {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
  </section>;
}
