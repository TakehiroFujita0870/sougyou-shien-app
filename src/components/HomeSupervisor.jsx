import { useEffect, useMemo, useState } from 'react';
import { SendHorizontal, Sparkles } from 'lucide-react';

import { createLocalContextSnapshot } from '../context/contextSnapshot';
import { Button } from './ui/Button';

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
  function assist() {
    const suggestion = input.trim()
      ? `${input.trim()}。誰の、どんな困りごとを、どう軽くするかも教えてください。`
      : '誰の、どんな困りごとを、どう軽くしたいか教えてください。';
    void updateInput(suggestion);
  }

  return <section aria-labelledby="home-supervisor-heading" className="mx-auto flex min-h-[calc(100vh-10rem)] w-full max-w-[900px] flex-col">
    <div className="px-1 pt-2"><p className="text-xs font-bold uppercase tracking-[0.16em] text-[var(--color-text-muted)]">Home</p><h1 id="home-supervisor-heading" className="mt-2 text-2xl font-semibold tracking-tight">Kadode AI</h1><p className="mt-2 text-sm leading-6 text-[var(--color-text-muted)]">アイデアを会話でほどき、判断する前に提案として確認します。</p></div>
    <ol className="mt-7 grid flex-1 content-start gap-4 pb-6" aria-label="会話履歴">
      {messages.length === 0 && <li className="py-12 text-center text-sm leading-6 text-[var(--color-text-muted)]">誰のどんな困りごとを解決したいか、自由に話してください。</li>}
      {messages.map((message, index) => <li key={`${message.role}-${index}`} className={`max-w-[82%] rounded-2xl px-4 py-3 text-sm leading-6 ${message.role === 'user' ? 'ml-auto bg-[var(--color-primary)] text-[var(--color-primary-foreground)]' : 'bg-[var(--color-muted)] text-[var(--color-text)]'}`}><strong className="block text-xs opacity-70">{message.role === 'user' ? 'あなた' : 'Kadode'}</strong><p>{message.content}</p></li>)}
      {state.proposals.map((proposal) => <li key={proposal.id} className="border-l-2 border-[var(--color-border)] py-1 pl-4"><p className="text-sm"><strong>推論:</strong> {proposal.inference}</p><p className="mt-1 text-xs text-[var(--color-text-muted)]"><strong>事実:</strong> {proposal.fact} · <strong>操作:</strong> {proposal.action}</p>{proposal.status === 'adopted' ? <p role="status" className="mt-2 text-sm font-bold text-emerald-800">Projectへ採用済み</p> : proposal.status === 'held' ? <p role="status" className="mt-2 text-sm font-bold">保留中</p> : proposal.status === 'rejected' ? <p role="status" className="mt-2 text-sm text-red-800">却下: {proposal.rejectionReason}</p> : <><label className="mt-3 block text-sm" htmlFor={`reject-${proposal.id}`}>却下理由（却下時は必須）</label><textarea id={`reject-${proposal.id}`} value={rejectReason} onChange={(event) => setRejectReason(event.target.value)} rows={2} className="mt-1 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-2 text-sm" /><div className="mt-3 flex flex-wrap gap-2"><Button type="button" onClick={() => void decide(proposal.id, 'adopted')} className="min-h-9 px-3">プロジェクトに採用</Button><Button type="button" variant="secondary" onClick={() => void decide(proposal.id, 'held')} className="min-h-9 px-3">保留</Button><Button type="button" variant="ghost" onClick={() => void decide(proposal.id, 'rejected')} className="min-h-9 px-3 text-red-800">理由付きで却下</Button></div></>}</li>)}
    </ol>
    <form onSubmit={send} className="sticky bottom-0 bg-[var(--color-background)] pb-2 pt-3">
      <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-2 shadow-sm">
        <label htmlFor="home-supervisor-message" className="sr-only">Kadode AIへのメッセージ</label>
        <textarea id="home-supervisor-message" value={input} onChange={(event) => { void updateInput(event.target.value); }} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void send(); } }} rows={2} maxLength={1000} className="w-full resize-none bg-transparent px-2 py-1 text-base leading-6 outline-none" placeholder="例：工場の保全担当者が故障履歴を探せない" />
        <div className="flex items-center justify-between gap-2"><p className="px-2 text-xs text-[var(--color-text-muted)]">Enterで送信、Shift+Enterで改行</p><div className="flex items-center gap-1"><Button type="button" variant="ghost" onClick={assist} className="min-h-9 gap-1 px-2 text-xs"><Sparkles size={15} aria-hidden="true" />AI補完</Button><span className="rounded-lg bg-[var(--color-muted)] px-2 py-1 text-xs text-[var(--color-text-muted)]">{modelKey || 'AIモデル'}</span><Button type="submit" aria-label="発言を送信" className="min-h-9 min-w-9 px-2"><SendHorizontal size={17} aria-hidden="true" /><span className="sr-only">発言を送信</span></Button></div></div>
      </div>
    </form>
    {error && <p role="alert" className="pt-2 text-sm text-red-700">{error}</p>}
  </section>;
}
