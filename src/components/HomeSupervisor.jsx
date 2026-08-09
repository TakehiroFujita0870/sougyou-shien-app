import { useEffect, useMemo, useState } from 'react';
import { createLocalContextSnapshot } from '../context/contextSnapshot';

const storageKey = 'kadode:home-supervisor';
const initialSnapshot = createLocalContextSnapshot({ ownerId: 'local-owner', surface: { name: 'Home', route: '/home' } });

export function proposeHomeAction(input, snapshot = initialSnapshot) {
  const action = /情報|プロフィール/.test(input) ? 'update_profile' : /プロジェクト|一覧/.test(input) ? 'inspect_projects' : /却下/.test(input) ? 'reject_candidate' : /保留/.test(input) ? 'hold_candidate' : /採用/.test(input) ? 'adopt_candidate' : 'ideate';
  return { id: crypto.randomUUID(), fact: `現在のsurface: ${snapshot.surface.name}`, inference: `入力を「${action}」として整理しました。`, action, confirmed: false };
}

export function createHomeSupervisorRepository(storage = globalThis.localStorage) {
  return { load: async () => JSON.parse(storage?.getItem(storageKey) || '{"messages":[],"proposals":[]}'), save: async (value) => { storage?.setItem(storageKey, JSON.stringify(value)); return value; } };
}

export function HomeSupervisor({ repository, snapshot = initialSnapshot }) {
  const [browserRepository] = useState(() => createHomeSupervisorRepository()); const activeRepository = repository ?? browserRepository;
  const [state, setState] = useState({ messages: [], proposals: [], input: '' }); const [input, setInput] = useState(''); const [error, setError] = useState('');
  useEffect(() => { activeRepository.load().then((value) => { setState(value); setInput(value.input || ''); }).catch(() => setError('会話を読み込めませんでした。')); }, [activeRepository]);
  const context = useMemo(() => JSON.stringify(snapshot), [snapshot]);
  async function send(event) { event.preventDefault(); const text = input.trim(); if (!text) return setError('発言を入力してください。'); const proposal = proposeHomeAction(text, snapshot); const next = { messages: [...state.messages, { role: 'user', content: text }], proposals: [proposal, ...state.proposals], input: '' }; try { await activeRepository.save(next); setState(next); setInput(''); setError(''); } catch { setError('端末内に保存できませんでした。'); } }
  async function confirm(id) { const next = { ...state, proposals: state.proposals.map((proposal) => proposal.id === id ? { ...proposal, confirmed: true } : proposal) }; try { await activeRepository.save(next); setState(next); } catch { setError('確認を保存できませんでした。'); } }
  return <section aria-labelledby="home-supervisor-heading" className="max-w-3xl"><p className="text-xs font-bold uppercase tracking-[0.16em] text-stone-500">Home</p><h1 id="home-supervisor-heading" className="mt-2 text-2xl font-semibold tracking-tight">Kadode AI</h1><p className="mt-2 text-sm text-stone-600">portfolio全体の次の検討を整理します。外部サービスへ送信しません。</p><form onSubmit={send} className="mt-6 rounded-2xl border border-stone-300 bg-white p-3"><label htmlFor="idea-message" className="sr-only">Kadode AIへのメッセージ</label><textarea id="idea-message" value={input} onChange={(event) => { const value = event.target.value; setInput(value); activeRepository.save({ ...state, input: value }); }} className="min-h-24 w-full resize-y p-2 text-base leading-6 outline-none" placeholder="アイデア、情報更新、プロジェクト確認を話してみる" /><p className="mt-2 text-xs text-stone-500">Enterで送信、Shift+Enterで改行</p><button className="mt-2 min-h-11 rounded-full bg-stone-900 px-5 py-2 text-sm font-bold text-white">発言を送信</button></form><p className="sr-only" data-testid="context-snapshot">{context}</p><div className="mt-5 grid gap-3">{state.proposals.map((proposal) => <article key={proposal.id} className="rounded-2xl border p-4"><p><strong>事実:</strong> {proposal.fact}</p><p><strong>推論:</strong> {proposal.inference}</p><p><strong>操作:</strong> {proposal.action}</p>{proposal.confirmed ? <p role="status">確認済み</p> : <button type="button" onClick={() => confirm(proposal.id)} className="mt-3 min-h-11 rounded-full border px-4 py-2 font-bold">アイデア候補として保存</button>}</article>)}</div>{error && <p role="alert">{error}</p>}</section>;
}
