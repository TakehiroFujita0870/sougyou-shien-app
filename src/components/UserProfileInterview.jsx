import { useEffect, useState } from 'react';

export const PROFILE_STEPS = [
  ['experience', 'これまでの経験を教えてください', '例: 営業を5年、飲食店での勤務経験があります'],
  ['strengths', '得意分野は何ですか？', '例: 人に話を聞くこと、Excelでの集計'],
  ['interests', '関心があるテーマを教えてください', '例: 地域の子育て、食品ロス'],
  ['time', '週に使える時間はどのくらいですか？', '例: 平日3時間、土日に6時間'],
  ['budget', '最初に使える資金の目安を教えてください', '例: 10万円まで。まずは小さく試したいです'],
  ['avoidances', '避けたい条件はありますか？', '例: 在庫を抱える事業、夜間の対応'],
];
export const EMPTY_PROFILE = Object.fromEntries(PROFILE_STEPS.map(([key]) => [key, '']));
export function validateProfileStep(values, index) {
  const value = values[PROFILE_STEPS[index][0]].trim();
  if (!value) return '短くても大丈夫です。あなたの言葉で入力してください。';
  return value.length > 300 ? '300文字以内で入力してください。' : '';
}
export function advanceProfile(state) {
  const error = validateProfileStep(state.values, state.step);
  if (error) return { ...state, error };
  const done = state.step === PROFILE_STEPS.length - 1;
  return { ...state, error: '', step: done ? state.step : state.step + 1, status: done ? 'completed' : 'in_progress' };
}
export function createBrowserProfileRepository(storage = globalThis.localStorage) {
  const key = 'kadode:user-profile';
  return { load: async () => { const item = storage?.getItem(key); return item ? JSON.parse(item) : null; }, save: async (profile) => { storage?.setItem(key, JSON.stringify(profile)); return profile; } };
}
export async function persistProfile(repository, profile) {
  try { return { profile: await repository.save(profile), error: '' }; }
  catch { return { profile: null, error: '保存できませんでした。接続を確認して、もう一度お試しください。' }; }
}
export function UserProfileInterview({ repository, onClose, onComplete }) {
  const [browserRepository] = useState(() => createBrowserProfileRepository());
  const activeRepository = repository ?? browserRepository;
  const [state, setState] = useState({ values: EMPTY_PROFILE, step: 0, status: 'loading', error: '' });
  const [saveError, setSaveError] = useState('');
  useEffect(() => { activeRepository.load().then((saved) => setState(saved ? { ...saved, status: saved.status === 'completed' ? 'completed' : 'in_progress', error: '' } : { values: EMPTY_PROFILE, step: 0, status: 'in_progress', error: '' })).catch(() => setState({ values: EMPTY_PROFILE, step: 0, status: 'in_progress', error: '' })); }, [activeRepository]);
  useEffect(() => { const escape = (event) => { if (event.key === 'Escape') onClose?.(); }; window.addEventListener('keydown', escape); return () => window.removeEventListener('keydown', escape); }, [onClose]);
  if (state.status === 'loading') return <div className="p-6">準備しています…</div>;
  const [field, question, placeholder] = PROFILE_STEPS[state.step];
  async function save(next) { setSaveError(''); const result = await persistProfile(activeRepository, next); if (result.error) return setSaveError(result.error); setState(result.profile); if (result.profile.status === 'completed') onComplete?.(result.profile.values); }
  function submit(event) { event.preventDefault(); const next = advanceProfile(state); if (next.error) return setState(next); save(next); }
  if (state.status === 'completed') return <section className="w-full min-w-0 max-w-full overflow-hidden rounded-3xl bg-white p-6 shadow-xl sm:max-w-2xl" aria-labelledby="profile-heading"><div className="flex min-w-0 justify-between gap-4"><div className="min-w-0"><p className="font-bold text-emerald-700">あなたの情報</p><h2 id="profile-heading" className="break-words text-2xl font-bold">プロフィールを更新</h2></div><button className="shrink-0" onClick={onClose} type="button" aria-label="ヒアリングを閉じる">閉じる</button></div><p className="mt-5 break-words rounded-2xl bg-emerald-50 p-4">入力内容は保存されています。変更したい項目を選んで更新できます。</p><div className="mt-4 grid min-w-0 gap-2">{PROFILE_STEPS.map(([key, label], step) => <button key={key} type="button" onClick={() => setState({ ...state, step, status: 'in_progress' })} className="min-w-0 rounded-xl border p-3 text-left"><strong className="break-words">{label}</strong><span className="block break-words text-sm">{state.values[key]}</span></button>)}</div></section>;
  return <section className="w-full min-w-0 max-w-full overflow-hidden rounded-3xl bg-white p-6 shadow-xl sm:max-w-2xl" aria-labelledby="profile-heading"><div className="flex min-w-0 justify-between gap-4"><div className="min-w-0"><p className="font-bold text-emerald-700">あなたの情報</p><h2 id="profile-heading" className="break-words text-2xl font-bold">一緒に整理していきましょう</h2></div><button className="shrink-0" onClick={onClose} type="button" aria-label="ヒアリングを閉じる">閉じる</button></div><form className="mt-6 min-w-0" onSubmit={submit} noValidate><p className="text-sm font-bold text-emerald-800">{state.step + 1} / {PROFILE_STEPS.length}</p><p id="profile-question" className="mt-3 break-words text-lg font-bold">{question}</p><textarea autoFocus value={state.values[field]} onChange={(event) => setState({ ...state, values: { ...state.values, [field]: event.target.value }, error: '' })} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); submit(event); } }} rows={4} maxLength={300} aria-invalid={Boolean(state.error)} aria-labelledby="profile-question" aria-describedby={state.error ? 'profile-error' : 'profile-help'} placeholder={placeholder} className="mt-3 w-full min-w-0 max-w-full rounded-2xl border p-4"/><p id="profile-help" className="mt-2 break-words text-xs">Enterで送信、Shift+Enterで改行。Escで閉じます。</p>{state.error && <p id="profile-error" role="alert" className="mt-2 break-words text-red-700">{state.error}</p>}{saveError && <p role="alert" className="mt-2 break-words text-red-700">{saveError}</p>}<div className="mt-5 flex min-w-0 flex-wrap gap-3"><button type="submit" className="rounded-full bg-emerald-800 px-5 py-3 font-bold text-white">{state.step === PROFILE_STEPS.length - 1 ? '保存して完了' : '送信して次へ'}</button>{state.step > 0 && <button type="button" onClick={() => setState({ ...state, step: state.step - 1, error: '' })}>戻る</button>}</div></form></section>;
}
