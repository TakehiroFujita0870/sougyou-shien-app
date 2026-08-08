import { useEffect, useMemo, useState } from 'react';

export const EMPTY_CANDIDATE = { title: '', summary: '', pain: '' };
const storageKey = 'kadode:idea-candidates';
const conversationStorageKey = 'kadode:idea-conversation';
export const normalizeTitle = (title) => title.trim().toLocaleLowerCase('ja-JP');
export function validateCandidate(candidate) {
  if (!candidate.title.trim()) return 'アイデア名を入力してください。';
  if (!candidate.summary.trim()) return 'アイデアの概要を入力してください。';
  return '';
}
export function createIdeaRepository(storage = globalThis.localStorage) {
  return { load: async () => JSON.parse(storage?.getItem(storageKey) || '[]'), save: async (items) => { storage?.setItem(storageKey, JSON.stringify(items)); return items; } };
}
export function createConversationRepository(storage = globalThis.localStorage) {
  return { load: async () => JSON.parse(storage?.getItem(conversationStorageKey) || '[]'), save: async (items) => { storage?.setItem(conversationStorageKey, JSON.stringify(items)); return items; } };
}
export function findDuplicate(items, candidate) { return items.find((item) => normalizeTitle(item.title) === normalizeTitle(candidate.title)); }
export function nextConversationQuestion(messages) {
  const text = messages.filter((message) => message.role === 'user').map((message) => message.content).join(' ');
  if (!/(誰|向け|担当者|利用者|お客|人)/.test(text)) return '誰が困っているかを、具体的な役割や場面で教えてください。';
  if (!/(困|手間|時間|不安|できない|探せない|負担)/.test(text)) return 'その人は今、何に困り、どんな損失や不安がありますか？';
  if (!/(解決|支援|アプリ|サービス|記録|自動|提供)/.test(text)) return 'その困りごとを、どんな方法で解決する案ですか？';
  return 'よい整理です。この案を候補としてプレビューし、保存できます。';
}
export function candidateFromConversation(messages) {
  const answers = messages.filter((message) => message.role === 'user').map((message) => message.content.trim()).filter(Boolean);
  const joined = answers.join(' ');
  return { title: answers[0]?.slice(0, 40) || '対話からのアイデア', summary: joined.slice(0, 300), pain: joined };
}
export async function saveCandidate(repository, items, candidate) {
  const error = validateCandidate(candidate); if (error) return { items, error };
  if (findDuplicate(items, candidate)) return { items, error: '同じ名前の候補があります。既存のカードを編集してください。' };
  const next = [{ ...candidate, id: crypto.randomUUID() }, ...items];
  try { return { items: await repository.save(next), error: '' }; } catch { return { items, error: '保存できませんでした。接続を確認して再試行してください。' }; }
}
export async function approveCandidate(repository, items, candidate) {
  const next = items.map((item) => item.id === candidate.id ? candidate : item);
  try { return { items: await repository.save(next), error: '' }; } catch { return { items, error: '更新を保存できませんでした。接続を確認して再試行してください。' }; }
}
export function IdeaCandidateWorkspace({ repository, conversationRepository }) {
  const [browserRepository] = useState(() => createIdeaRepository());
  const [browserConversationRepository] = useState(() => createConversationRepository());
  const activeRepository = repository ?? browserRepository;
  const activeConversationRepository = conversationRepository ?? browserConversationRepository;
  const [items, setItems] = useState([]); const [messages, setMessages] = useState([]); const [input, setInput] = useState(''); const [selected, setSelected] = useState(null); const [error, setError] = useState('');
  useEffect(() => { activeRepository.load().then(setItems).catch(() => setError('候補を読み込めませんでした。')); }, [activeRepository]);
  useEffect(() => { activeConversationRepository.load().then(setMessages).catch(() => setError('会話を読み込めませんでした。')); }, [activeConversationRepository]);
  useEffect(() => { const close = (event) => { const target = event.target; if (event.key === 'Escape' && !(target instanceof Element && target.closest('textarea, input'))) setSelected(null); }; window.addEventListener('keydown', close); return () => window.removeEventListener('keydown', close); }, []);
  const preview = useMemo(() => candidateFromConversation(messages), [messages]);
  async function send(event) { event?.preventDefault(); const content = input.trim(); if (!content) { setError('発言を入力してください。'); return; } const user = { role: 'user', content }; const next = [...messages, user]; const withReply = [...next, { role: 'assistant', content: nextConversationQuestion(next) }]; try { await activeConversationRepository.save(withReply); setMessages(withReply); setInput(''); setError(''); } catch { setError('会話を保存できませんでした。再試行してください。'); } }
  async function create() { const result = await saveCandidate(activeRepository, items, preview); setError(result.error); setItems(result.items); if (!result.error) setSelected(result.items[0]); }
  async function approve() { const result = await approveCandidate(activeRepository, items, selected); setError(result.error); setItems(result.items); if (!result.error) setSelected(result.items.find((item) => item.id === selected.id)); }
  return <section className="grid gap-5 lg:grid-cols-[1fr_1fr]" aria-label="アイデアストック"><div className="rounded-3xl border bg-white p-5 shadow-sm"><h2 className="text-xl font-bold">アイデアを話してみる</h2><p className="mt-1 text-sm text-stone-600">この対話は端末内だけで処理・保存されます。</p><ol className="mt-4 grid max-h-80 gap-3 overflow-y-auto" aria-label="会話履歴">{messages.length === 0 && <li className="text-sm text-stone-600">誰のどんな困りごとを解決したいか、自由に書いてください。</li>}{messages.map((message, index) => <li key={index} className={`rounded-2xl p-3 text-sm ${message.role === 'user' ? 'ml-8 bg-emerald-100' : 'mr-8 bg-stone-100'}`}><strong>{message.role === 'user' ? 'あなた' : 'Kadode'}</strong><p>{message.content}</p></li>)}</ol><form onSubmit={send} className="mt-4"><label className="text-sm font-bold" htmlFor="idea-message">発言</label><textarea id="idea-message" value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); send(); } }} maxLength={1000} rows={3} className="mt-1 w-full rounded-xl border p-3 focus:border-emerald-700 focus:ring-2 focus:ring-emerald-100" placeholder="例：工場の保全担当者が故障履歴を探せない" /><p className="mt-1 text-xs text-stone-500">Enterで送信、Shift+Enterで改行。外部サービスへ送信しません。</p><button className="mt-3 min-h-11 rounded-full bg-emerald-800 px-5 py-3 font-bold text-white">発言を送信</button></form></div><div className="rounded-3xl border bg-white p-5 shadow-sm"><h2 className="text-xl font-bold">アイデアストック</h2>{messages.some((message) => message.role === 'user') && <div className="mt-4 rounded-2xl bg-emerald-50 p-4"><h3 className="font-bold">保存前プレビュー</h3><p className="mt-2 font-bold">{preview.title}</p><p className="mt-1 text-sm">{preview.summary}</p><p className="mt-2 text-sm text-stone-700">ペイン: {preview.pain}</p><button type="button" onClick={create} className="mt-4 min-h-11 rounded-full bg-emerald-800 px-5 py-3 font-bold text-white">アイデア候補として保存</button></div>}{items.length === 0 && <p className="mt-4 text-stone-600">まだ候補はありません。</p>}<div className="mt-4 grid gap-3">{items.map((item) => <button key={item.id} type="button" onClick={() => setSelected({ ...item })} className="min-h-11 rounded-2xl border p-4 text-left hover:border-emerald-600"><strong>{item.title}</strong><span className="mt-1 block text-sm text-stone-600">{item.summary}</span></button>)}</div>{selected && <div className="mt-5 rounded-2xl bg-emerald-50 p-4"><h3 className="font-bold">仮説カード（編集案）</h3>{[['title','アイデア名'],['summary','概要'],['pain','ペイン']].map(([name,label]) => <label key={name} className="mt-3 block text-sm font-bold">{label}<textarea name={name} value={selected[name]} onChange={(event) => setSelected({ ...selected, [name]: event.target.value })} rows={2} className="mt-1 w-full rounded-xl border p-3 font-normal" /></label>)}<button type="button" onClick={approve} className="mt-4 min-h-11 rounded-full bg-emerald-800 px-5 py-3 font-bold text-white">内容を確認して更新</button></div>}{error && <p role="alert" className="mt-3 text-sm text-red-700">{error}</p>}</div></section>;
}
