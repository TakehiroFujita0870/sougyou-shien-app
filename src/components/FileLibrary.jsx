import { useState } from 'react';

const MAX_BYTES = 25 * 1024 * 1024;
const ALLOWED = ['pdf', 'docx', 'txt', 'csv'];

export function validateUpload(file) {
  const extension = file.name.split('.').pop()?.toLowerCase();
  if (!ALLOWED.includes(extension)) return { reason: 'PDF、DOCX、TXT、CSVのみ登録できます。' };
  if (file.size > MAX_BYTES) return { reason: '25 MiB以下のファイルを選んでください。' };
  return {};
}

export function createFakeDocumentRepository(seed = []) {
  let documents = [...seed];
  const find = (id) => documents.find((document) => document.id === id);
  const replace = (next) => { documents = documents.map((document) => document.id === next.id ? next : document); return next; };
  return {
    add: async (file) => { const document = { id: crypto.randomUUID(), name: file.name, version: 1, state: 'processing' }; documents = [...documents, document]; return document; },
    retry: async (id) => replace({ ...find(id), state: 'processing' }),
    addVersion: async (id, file) => replace({ ...find(id), name: file.name, version: find(id).version + 1, state: 'processing' }),
    remove: async (id) => replace({ ...find(id), state: 'deleted' }),
  };
}

const stateLabel = { processing: '解析中', searchable: '検索可能', failed: '解析に失敗', deleted: '削除済み' };

export function FileLibrary({ repository = createFakeDocumentRepository(), initialDocuments = [] }) {
  const [documents, setDocuments] = useState(initialDocuments);
  const [error, setError] = useState('');
  const [deleteTarget, setDeleteTarget] = useState(null);
  const update = (next) => setDocuments((current) => current.map((item) => item.id === next.id ? next : item));
  async function upload(file, versionOf) {
    const validation = validateUpload(file); if (validation.reason) return setError(validation.reason);
    setError(''); const next = versionOf ? await repository.addVersion(versionOf.id, file) : await repository.add(file);
    setDocuments((current) => versionOf ? current.map((item) => item.id === next.id ? next : item) : [...current, next]);
  }
  return <section className="w-full max-w-3xl rounded-3xl border border-stone-200 bg-white p-5 shadow-sm sm:p-7" aria-labelledby="files-heading">
    <p className="text-xs font-bold tracking-[0.16em] text-emerald-700">あなたの資料</p><h2 id="files-heading" className="mt-2 text-2xl font-bold">ファイルを調査に使う</h2>
    <p className="mt-2 text-sm leading-6 text-stone-600">PDF、DOCX、TXT、CSV（25 MiB以下）。外部サービスへは送信しません。</p>
    <label className="mt-5 inline-flex cursor-pointer rounded-full bg-emerald-800 px-5 py-3 font-bold text-white"><span>資料を追加</span><input className="sr-only" type="file" accept=".pdf,.docx,.txt,.csv" onChange={(event) => event.target.files[0] && upload(event.target.files[0])} /></label>
    {error && <p role="alert" className="mt-3 text-sm font-bold text-red-700">{error}</p>}
    <ul className="mt-6 grid gap-3" aria-label="登録済み資料">{documents.map((document) => <li key={document.id} className="rounded-2xl border border-stone-200 p-4"><div className="flex flex-wrap items-start justify-between gap-3"><div><strong>{document.name}</strong><p className="mt-1 text-sm text-stone-600">v{document.version} · {stateLabel[document.state]}</p></div><div className="flex flex-wrap gap-2">{document.state === 'failed' && <button type="button" onClick={async () => update(await repository.retry(document.id))} className="rounded-full border px-3 py-2 text-sm font-bold">再試行</button>}{document.state !== 'deleted' && <label className="cursor-pointer rounded-full border px-3 py-2 text-sm font-bold">新版<input className="sr-only" type="file" accept=".pdf,.docx,.txt,.csv" onChange={(event) => event.target.files[0] && upload(event.target.files[0], document)} /></label>}{document.state !== 'deleted' && <button type="button" onClick={() => setDeleteTarget(document)} className="rounded-full border border-red-200 px-3 py-2 text-sm font-bold text-red-800">削除</button>}</div></div></li>)}</ul>
    {deleteTarget && <div role="dialog" aria-modal="true" aria-labelledby="delete-heading" className="mt-5 rounded-2xl border border-red-200 bg-red-50 p-4"><h3 id="delete-heading" className="font-bold">削除確認</h3><p className="mt-1 text-sm">{deleteTarget.name}の原本、抽出本文、断片、埋め込みを削除対象にします。</p><button type="button" onClick={async () => { update(await repository.remove(deleteTarget.id)); setDeleteTarget(null); }} className="mt-3 rounded-full bg-red-800 px-4 py-2 text-sm font-bold text-white">削除を確定</button><button type="button" onClick={() => setDeleteTarget(null)} className="ml-3 text-sm underline">戻る</button></div>}
  </section>;
}
