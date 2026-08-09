import { useEffect, useMemo, useRef, useState } from 'react';
import { Mic, SendHorizontal } from 'lucide-react';

import { createLocalContextSnapshot } from '../context/contextSnapshot';
import { AiComposer } from './AiComposer';
import { createHomeConversationRepository, EMPTY_HOME_CONVERSATION_STATE } from './homeConversationRepository';
import { Button } from './ui/Button';

const initialSnapshot = createLocalContextSnapshot({ ownerId: 'local-owner', surface: { name: 'Home', route: '/home' } });
const emptyState = EMPTY_HOME_CONVERSATION_STATE;
const promptPresets = [
  'これまでの経験から、誰かの役に立てそうなことを一緒に考えたい',
  '仕事の中で何度も感じる不便を、事業にできるか相談したい',
  '今の暮らしと両立できる、小さな一歩から考えたい',
];
const ephemeralDraftRepository = { loadDraft: async () => '', saveDraft: async (value) => value };

export { createHomeConversationRepository } from './homeConversationRepository';

export function proposeHomeAction(input, snapshot = initialSnapshot) {
  const action = /プロジェクト.*(一覧|確認)|一覧.*確認/.test(input) ? 'inspect_projects' : 'ideate';
  return {
    id: crypto.randomUUID(),
    title: input.trim(),
    fact: `現在のsurface: ${snapshot.surface.name}`,
    inference: `入力を「${action}」として整理しました。`,
    reason: '',
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

export function HomeSupervisor({ repository, snapshot = initialSnapshot, onProjectAdopt, modelKey, models = [], onModelChange }) {
  const [browserRepository] = useState(() => createHomeConversationRepository());
  const activeRepository = repository ?? browserRepository;
  const draftRepository = typeof activeRepository.loadDraft === 'function' && typeof activeRepository.saveDraft === 'function' ? activeRepository : ephemeralDraftRepository;
  const [state, setState] = useState(emptyState);
  const [input, setInput] = useState('');
  const [rejectReason, setRejectReason] = useState('');
  const [error, setError] = useState('');
  const [hydrationPhase, setHydrationPhase] = useState('loading');
  const [hydrationAttempt, setHydrationAttempt] = useState(0);
  const stateRef = useRef(emptyState);
  const inputRef = useRef('');
  const mutationQueueRef = useRef(Promise.resolve());
  const mutationRevisionRef = useRef(0);
  const draftQueueRef = useRef(Promise.resolve());
  const hasLocalDraftMutationRef = useRef(false);
  const loadGenerationRef = useRef(0);

  useEffect(() => {
    const generation = ++loadGenerationRef.current;
    setHydrationPhase('loading');
    Promise.all([activeRepository.load(), draftRepository.loadDraft()]).then(([value, draft]) => {
      if (generation !== loadGenerationRef.current) return;
      stateRef.current = value;
      setState(value);
      if (!hasLocalDraftMutationRef.current) {
        inputRef.current = draft;
        setInput(draft);
      }
      setHydrationPhase('ready');
      const adopted = value.proposals.find(({ status }) => status === 'adopted');
      if (adopted) onProjectAdopt?.(adopted);
    }).catch(() => {
      if (generation !== loadGenerationRef.current) return;
      setHydrationPhase('error');
      setError('会話を読み込めませんでした。');
    });
    return () => { loadGenerationRef.current += 1; };
  }, [activeRepository, draftRepository, hydrationAttempt, onProjectAdopt]);

  const messages = useMemo(() => state.messages, [state.messages]);
  function updateInput(value) {
    hasLocalDraftMutationRef.current = true;
    inputRef.current = value; setInput(value);
    draftQueueRef.current = draftQueueRef.current.catch(() => undefined).then(() => draftRepository.saveDraft(value)).catch(() => setError('下書きを保存できませんでした。'));
  }
  function mutateConversation(update, failureMessage = '会話を保存できませんでした。再試行してください。') {
    const next = update(stateRef.current);
    const revision = ++mutationRevisionRef.current;
    stateRef.current = next; setState(next);
    const persisted = mutationQueueRef.current.catch(() => undefined).then(() => activeRepository.save(next));
    mutationQueueRef.current = persisted.catch(() => undefined);
    persisted.then((saved) => {
      if (revision !== mutationRevisionRef.current) return;
      stateRef.current = saved; setState(saved); setError('');
    }).catch(() => setError(failureMessage));
    return { next, persisted };
  }
  async function send(event) {
    event?.preventDefault();
    const content = inputRef.current.trim();
    if (!content) { setError('発言を入力してください。'); return; }
    updateInput('');
    mutateConversation((current) => {
      const nextMessages = [...current.messages, { role: 'user', content }];
      return { messages: [...nextMessages, { role: 'assistant', content: nextQuestion(nextMessages) }], proposals: [proposeHomeAction(content, snapshot), ...current.proposals] };
    });
  }
  async function decide(id, status) {
    if (status === 'rejected' && !rejectReason.trim()) { setError('却下理由を入力してください。'); return; }
    const reason = rejectReason.trim();
    const { next, persisted } = mutateConversation((current) => ({ ...current, proposals: current.proposals.map((proposal) => proposal.id === id ? { ...proposal, status, confirmed: status === 'adopted', ...(status === 'rejected' ? { rejectionReason: reason } : {}) } : proposal) }), '判断を保存できませんでした。再試行してください。');
    setRejectReason('');
    if (status === 'adopted') {
      try { await persisted; onProjectAdopt?.(next.proposals.find((proposal) => proposal.id === id)); } catch { /* visible persistence error is set by the queue */ }
    }
  }
  const isEmpty = messages.length === 0 && state.proposals.length === 0;
  return <section aria-labelledby="home-supervisor-heading" data-home-state={isEmpty ? 'empty' : 'populated'} className={`mx-auto flex h-[calc(100dvh-4rem)] min-h-0 w-full max-w-[900px] flex-col overflow-hidden ${isEmpty ? 'justify-center pb-[10vh]' : ''}`}>
    <div className={`shrink-0 px-1 ${isEmpty ? 'mx-auto w-full max-w-[840px] text-center' : 'pt-2'}`}><p className="text-xs font-bold uppercase tracking-[0.16em] text-[var(--color-text-muted)]">Home</p><h1 id="home-supervisor-heading" className="mt-2 text-2xl font-semibold tracking-tight">Kadode AI</h1><p className="mt-2 text-sm leading-6 text-[var(--color-text-muted)]">アイディエーションからプロジェクト管理まで、あらゆる相談役</p></div>
    <ol data-home-scroll-region="true" className={`grid min-h-0 gap-4 overflow-y-auto overscroll-contain pr-2 ${isEmpty ? 'sr-only' : 'mt-5 flex-1 content-start pb-4'}`} aria-label="会話履歴">
      {messages.map((message, index) => <li key={`${message.role}-${index}`} className={`max-w-[82%] rounded-2xl px-4 py-3 text-sm leading-6 ${message.role === 'user' ? 'ml-auto bg-[var(--color-primary)] text-[var(--color-primary-foreground)]' : 'bg-[var(--color-muted)] text-[var(--color-text)]'}`}><strong className="block text-xs opacity-70">{message.role === 'user' ? 'あなた' : 'Kadode'}</strong><p>{message.content}</p></li>)}
      {state.proposals.map((proposal) => <li key={proposal.id} className="border-l-2 border-[var(--color-border)] py-1 pl-4"><p className="text-sm"><strong>推論:</strong> {proposal.inference}</p><p className="mt-1 text-xs text-[var(--color-text-muted)]"><strong>事実:</strong> {proposal.fact} · <strong>操作:</strong> {proposal.action}</p>{proposal.status === 'adopted' ? <p role="status" className="mt-2 text-sm font-bold text-emerald-800">Projectへ採用済み</p> : proposal.status === 'held' ? <p role="status" className="mt-2 text-sm font-bold">保留中</p> : proposal.status === 'rejected' ? <p role="status" className="mt-2 text-sm text-red-800">却下: {proposal.rejectionReason}</p> : <><label className="mt-3 block text-sm" htmlFor={`reject-${proposal.id}`}>却下理由（却下時は必須）</label><textarea id={`reject-${proposal.id}`} value={rejectReason} onChange={(event) => setRejectReason(event.target.value)} rows={2} className="mt-1 w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-2 text-sm" /><div className="mt-3 flex flex-wrap gap-2"><Button type="button" onClick={() => void decide(proposal.id, 'adopted')} className="min-h-9 px-3">プロジェクトに採用</Button><Button type="button" variant="secondary" onClick={() => void decide(proposal.id, 'held')} className="min-h-9 px-3">保留</Button><Button type="button" variant="ghost" onClick={() => void decide(proposal.id, 'rejected')} className="min-h-9 px-3 text-red-800">理由付きで却下</Button></div></>}</li>)}
    </ol>
    <AiComposer id="home-supervisor-message" label="Kadode AIへのメッセージ" value={input} onValueChange={updateInput} onSubmit={() => void send()} disabled={hydrationPhase === 'loading'} rows={5} maxLength={1000} outerClassName={`shrink-0 ${isEmpty ? 'mx-auto mt-6 w-full max-w-[840px]' : 'mt-auto bg-[var(--color-background)] pt-3'}`} formData={{ 'data-home-composer': 'true', 'aria-busy': hydrationPhase === 'loading' }} textareaClassName="min-h-36 resize-none" actionsClassName="mt-2" placeholder="誰の、どんな困りごとを解決したいか、思いつくことを何でも教えてください。" modelKey={modelKey} models={models} onModelChange={onModelChange} modelMenuAriaLabel="AIモデルを選択" showSelectedModel sendAriaLabel="発言を送信" sendIcon={<><SendHorizontal size={17} aria-hidden="true" /><span className="sr-only">発言を送信</span></>} leadingActions={<Button type="button" variant="ghost" className="min-h-9 min-w-9 px-2" aria-label="音声入力（準備中）" title="音声入力（準備中）" disabled><Mic size={17} aria-hidden="true" /></Button>}><div className="mt-2 flex flex-wrap gap-2" aria-label="会話のきっかけ">{promptPresets.map((preset) => <Button key={preset} type="button" variant="secondary" disabled={hydrationPhase === 'loading'} className="min-h-8 rounded-full px-3 py-1 text-xs" onClick={() => updateInput(preset)}>{preset}</Button>)}</div></AiComposer>
    {error && <div role="alert" className="flex items-center gap-2 pt-2 text-sm text-red-700"><span>{error}</span>{hydrationPhase === 'error' && <Button type="button" variant="secondary" className="min-h-9 px-3 text-xs" onClick={() => { setError(''); setHydrationPhase('loading'); setHydrationAttempt((value) => value + 1); }}>再試行</Button>}</div>}
  </section>;
}
