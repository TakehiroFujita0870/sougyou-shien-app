import { useEffect, useState } from 'react';

export const EMPTY_CANDIDATE = { title: '', summary: '', pain: '' };
const storageKey = 'kadode:idea-candidates';
export const normalizeTitle = (title) => title.trim().toLocaleLowerCase('ja-JP');
export function validateCandidate(candidate) {
  if (!candidate.title.trim()) return 'アイデア名を入力してください。';
  if (!candidate.summary.trim()) return 'アイデアの概要を入力してください。';
  return '';
}
export function createIdeaRepository(storage = globalThis.localStorage) {
  return { load: async () => JSON.parse(storage?.getItem(storageKey) || '[]'), save: async (items) => { storage?.setItem(storageKey, JSON.stringify(items)); return items; } };
}
export function findDuplicate(items, candidate) { return items.find((item) => normalizeTitle(item.title) === normalizeTitle(candidate.title)); }
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
export function IdeaCandidateWorkspace({ repository = createIdeaRepository() }) {
  const [items, setItems] = useState([]); const [draft, setDraft] = useState(EMPTY_CANDIDATE); const [selected, setSelected] = useState(null); const [error, setError] = useState('');
  useEffect(() => { repository.load().then(setItems).catch(() => setError('候補を読み込めませんでした。')); }, [repository]);
  useEffect(() => { const close = (event) => { if (event.key === 'Escape') setSelected(null); }; window.addEventListener('keydown', close); return () => window.removeEventListener('keydown', close); }, []);
  const change = (event) => setDraft({ ...draft, [event.target.name]: event.target.value });
  async function create(event) { event.preventDefault(); const result = await saveCandidate(repository, items, draft); setError(result.error); setItems(result.items); if (!result.error) { setSelected(result.items[0]); setDraft(EMPTY_CANDIDATE); } }
  async function approve() { const result = await approveCandidate(repository, items, selected); setError(result.error); setItems(result.items); if (!result.error) setSelected(result.items.find((item) => item.id === selected.id)); }
  return <section className="grid gap-5 lg:grid-cols-[.8fr_1.2fr]" aria-label="アイデアストック"><form onSubmit={create} className="rounded-3xl border bg-white p-5 shadow-sm"><h2 className="text-xl font-bold">対話から候補を保存</h2><p className="mt-1 text-sm text-stone-600">外部サービスには送信しません。</p>{[['title','アイデア名'],['summary','概要'],['pain','誰の、何のペインか']].map(([name,label]) => <label key={name} className="mt-4 block text-sm font-bold">{label}<textarea name={name} value={draft[name]} onChange={change} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey && name === 'title') { event.preventDefault(); create(event); } }} rows={name === 'title' ? 2 : 3} className="mt-1 w-full rounded-xl border p-3 font-normal" /></label>)}<p className="mt-2 text-xs text-stone-500">タイトル欄はEnterで保存、Shift+Enterで改行。Escで編集を閉じます。</p>{error && <p role="alert" className="mt-2 text-sm text-red-700">{error}</p>}<button className="mt-4 rounded-full bg-emerald-800 px-5 py-3 font-bold text-white">候補を保存</button></form><div className="rounded-3xl border bg-white p-5 shadow-sm"><h2 className="text-xl font-bold">アイデアストック</h2>{items.length === 0 && <p className="mt-4 text-stone-600">まだ候補はありません。</p>}<div className="mt-4 grid gap-3">{items.map((item) => <button key={item.id} type="button" onClick={() => setSelected({ ...item })} className="rounded-2xl border p-4 text-left hover:border-emerald-600"><strong>{item.title}</strong><span className="mt-1 block text-sm text-stone-600">{item.summary}</span></button>)}</div>{selected && <div className="mt-5 rounded-2xl bg-emerald-50 p-4"><h3 className="font-bold">仮説カード（編集案）</h3>{[['title','アイデア名'],['summary','概要'],['pain','ペイン']].map(([name,label]) => <label key={name} className="mt-3 block text-sm font-bold">{label}<textarea name={name} value={selected[name]} onChange={(event) => setSelected({ ...selected, [name]: event.target.value })} rows={2} className="mt-1 w-full rounded-xl border p-3 font-normal" /></label>)}<button type="button" onClick={approve} className="mt-4 rounded-full bg-emerald-800 px-5 py-3 font-bold text-white">内容を確認して更新</button></div>}</div></section>;
}
