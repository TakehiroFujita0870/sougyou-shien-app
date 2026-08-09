import { useEffect, useRef, useState } from 'react';
import { SendHorizontal, Sparkles, Upload } from 'lucide-react';
import { Badge } from './ui/Badge';
import { Button } from './ui/Button';
import { Card } from './ui/Card';
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogTitle } from './ui/Dialog';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuTrigger } from './ui/DropdownMenu';
import { createKnowledgeMetadataRepository } from './knowledgeMetadataRepository';

const MAX_FILE_SIZE = 10 * 1024 * 1024;
const stateLabel = { metadata_only: '端末内メタデータ', processing: '処理中', searchable: '検索可能', failed: '確認が必要' };

function assetMetadata(asset) {
  return { id: asset.id, name: asset.name, version: asset.version, state: asset.state, extractedTextState: asset.state === 'searchable' ? 'ready' : 'pending', indexState: asset.state === 'searchable' ? 'ready' : 'pending' };
}

export function createLocalUploadMetadata(file) {
  const name = String(file?.name ?? '').trim();
  const extension = name.split('.').at(-1)?.toLowerCase();
  if (!['pdf', 'docx'].includes(extension)) throw new Error('PDFまたはDOCXを選択してください。');
  if (!Number.isFinite(file?.size) || file.size > MAX_FILE_SIZE) throw new Error('10 MiB以下の資料を選択してください。');
  const lastModified = Number.isFinite(file?.lastModified) ? file.lastModified : 0;
  return {
    id: `local-file:${encodeURIComponent(name.toLocaleLowerCase())}:${file.size}:${lastModified}`,
    name,
    version: 1,
    state: 'metadata_only',
    mediaType: extension,
    sizeBytes: file.size,
    lastModified,
    extractedTextState: 'pending',
    indexState: 'pending',
  };
}

function formatFileSize(sizeBytes) {
  if (!Number.isFinite(sizeBytes)) return 'サイズ情報なし';
  return `${Math.max(1, Math.ceil(sizeBytes / 1024))} KB`;
}

export function KnowledgeSurface({ fixture, repository, ownerId = 'admin-demo-owner', spaceId = 'admin-demo-space', onSend = () => {}, modelKey = 'gpt-5.6-terra', models = [], onModelChange }) {
  const [message, setMessage] = useState('');
  const [removeRequested, setRemoveRequested] = useState(null);
  const [documents, setDocuments] = useState([]);
  const [fixtureDeleted, setFixtureDeleted] = useState(false);
  const [persistenceError, setPersistenceError] = useState(false);
  const [notice, setNotice] = useState('');
  const repositoryRef = useRef(repository ?? createKnowledgeMetadataRepository({ ownerId, spaceId }));
  const fileInputRef = useRef(null);
  const asset = fixture?.asset;
  const modelLabel = models.find((model) => model.logicalKey === modelKey)?.displayName ?? 'GPT-5.6 Terra';

  useEffect(() => {
    let active = true;
    const localRepository = repositoryRef.current;
    localRepository.load().then(() => {
      if (!active) return;
      setDocuments(localRepository.list());
      setFixtureDeleted(localRepository.find(asset?.id)?.state === 'deleted');
      setPersistenceError(Boolean(localRepository.getLastError?.()));
    }).catch(() => { if (active) setPersistenceError(true); });
    return () => { active = false; };
  }, [asset?.id]);

  const fixtureDocument = asset && !fixtureDeleted && asset.state !== 'deleted' ? { ...asset, kind: 'fixture', references: asset.references?.filter((reference) => reference.status !== 'unavailable') ?? [] } : null;
  const visibleDocuments = [...(fixtureDocument ? [fixtureDocument] : []), ...documents.filter((document) => document.id !== asset?.id).map((document) => ({ ...document, kind: 'local', references: [] }))];

  function submit(event) {
    event.preventDefault();
    const value = message.trim();
    if (!value) return;
    onSend(value);
    setMessage('');
  }

  async function addFile(event) {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    try {
      const metadata = createLocalUploadMetadata(file);
      const existing = repositoryRef.current.find(metadata.id);
      await repositoryRef.current.add(metadata);
      setDocuments(repositoryRef.current.list());
      setPersistenceError(false);
      setNotice(existing ? 'この資料はすでに追加されています。' : '資料名とメタデータを端末内に追加しました。本文は保存・送信していません。');
    } catch (error) {
      setPersistenceError(true);
      setNotice(error instanceof Error ? error.message : '資料を追加できませんでした。ページを再読み込みしてから、もう一度お試しください。');
    }
  }

  async function confirmRemoval() {
    const target = removeRequested;
    if (!target) return;
    try {
      const fallback = target.kind === 'fixture' ? assetMetadata(target) : target;
      const deletedMetadata = await repositoryRef.current.delete(target.id, fallback);
      if (!deletedMetadata) throw new Error('Metadata could not be deleted');
      setDocuments(repositoryRef.current.list());
      if (target.id === asset?.id) setFixtureDeleted(true);
      setPersistenceError(false);
      setNotice('資料を端末内の一覧から削除しました。');
      setRemoveRequested(null);
    } catch {
      setPersistenceError(true);
      setNotice('削除は反映されていません。ページを再読み込みしてから、もう一度お試しください。');
      setRemoveRequested(null);
    }
  }

  return <section aria-labelledby="knowledge-heading" className="mx-auto grid w-full max-w-6xl gap-6 pb-36">
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div><p className="text-xs font-semibold uppercase tracking-[0.18em] text-[var(--color-text-muted)]">Knowledge</p><h1 id="knowledge-heading" className="mt-3 text-3xl font-semibold tracking-tight">知識を育てる</h1><p className="mt-2 max-w-2xl text-sm leading-6 text-[var(--color-text-muted)]">資料と判断を同じ場所で振り返れます。追加した資料の本文はこの端末に保存・送信しません。</p></div>
      <div><label className="sr-only" htmlFor="knowledge-file-picker">追加する資料を選択</label><input ref={fileInputRef} id="knowledge-file-picker" className="sr-only" type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" aria-describedby="knowledge-file-help" onChange={(event) => void addFile(event)} /><Button type="button" className="gap-2" onClick={() => fileInputRef.current?.click()}><Upload className="size-4" aria-hidden="true" />資料を追加</Button><p id="knowledge-file-help" className="mt-2 max-w-56 text-xs leading-5 text-[var(--color-text-muted)]">PDF・DOCX、10 MiB以下。本文は保存・送信しません。</p></div>
    </header>

    {(notice || persistenceError) && <p role={persistenceError ? 'alert' : 'status'} className={`text-sm ${persistenceError ? 'text-[var(--color-destructive)]' : 'text-[var(--color-text-muted)]'}`}>{notice || '保存状態を確認できません。ページを再読み込みしてから、もう一度お試しください。'}</p>}

    {visibleDocuments.length === 0 ? <Card className="p-6"><h2 className="text-lg font-semibold">まだ資料はありません</h2><p className="mt-2 text-sm leading-6 text-[var(--color-text-muted)]">資料を追加すると、ファイル名と端末内メタデータをここで確認できます。</p></Card> : <div className="grid gap-6 lg:grid-cols-[minmax(0,1.15fr)_minmax(18rem,.85fr)]">
      <div className="grid gap-4">{visibleDocuments.map((document) => <Card key={document.id} className="p-6"><div className="flex flex-wrap items-start justify-between gap-4"><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><h2 className="truncate text-lg font-semibold">{document.name}</h2><Badge variant="outline">{stateLabel[document.state] ?? document.state}</Badge></div><p className="mt-2 text-sm text-[var(--color-text-muted)]">{document.kind === 'local' ? `${document.mediaType?.toUpperCase() ?? '資料'} · ${formatFileSize(document.sizeBytes)} · 本文は未保存` : `バージョン ${document.version} · このspaceで参照可能`}</p></div><Button variant="secondary" onClick={() => setRemoveRequested(document)}>削除</Button></div>{document.references.length > 0 && <div className="mt-6 border-t border-[var(--color-border-subtle)] pt-5"><h3 className="text-sm font-semibold">参照元</h3><ul aria-label={`${document.name}の利用可能な出典`} className="mt-3 grid gap-2 text-sm text-[var(--color-text-muted)]">{document.references.map((reference) => <li key={`${reference.kind}-${reference.sourceId}-${reference.locator}`} className="rounded-lg bg-[var(--color-muted)] px-3 py-2"><span className="font-medium text-[var(--color-text)]">{reference.kind}</span> · {reference.locator}</li>)}</ul></div>}</Card>)}</div>
      {fixture && <Card className="p-6"><p className="text-xs font-semibold uppercase tracking-[0.16em] text-[var(--color-text-muted)]">Project context</p><h2 className="mt-3 text-lg font-semibold">{fixture.project.name}</h2><p className="mt-2 text-sm leading-6 text-[var(--color-text-muted)]">{fixture.project.summary}</p><dl className="mt-6 grid gap-4 border-t border-[var(--color-border-subtle)] pt-5 text-sm"><div><dt className="font-medium text-[var(--color-text-muted)]">背景</dt><dd className="mt-1">{fixture.decision.background}</dd></div><div><dt className="font-medium text-[var(--color-text-muted)]">判断</dt><dd className="mt-1">{fixture.decision.judgement}</dd></div><div><dt className="font-medium text-[var(--color-text-muted)]">理由</dt><dd className="mt-1">{fixture.decision.reason}</dd></div></dl></Card>}
    </div>}

    <Dialog open={Boolean(removeRequested)} onOpenChange={(open) => { if (!open) setRemoveRequested(null); }}><DialogContent><DialogTitle className="text-lg font-semibold">この資料を削除しますか？</DialogTitle><DialogDescription className="mt-2 text-sm leading-6 text-[var(--color-text-muted)]">資料名と端末内メタデータをこのspaceから削除します。この操作は元に戻せません。</DialogDescription><div className="mt-5 flex flex-wrap gap-3"><Button onClick={() => void confirmRemoval()}>削除を確定</Button><DialogClose asChild><Button variant="secondary">キャンセル</Button></DialogClose></div></DialogContent></Dialog>

    <form onSubmit={submit} className="sticky bottom-5 z-10 mx-auto w-full max-w-4xl rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-3 shadow-lg"><label htmlFor="knowledge-composer" className="sr-only">KnowledgeについてKadode AIに相談</label><textarea id="knowledge-composer" value={message} onChange={(event) => setMessage(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} className="min-h-24 w-full resize-y bg-transparent px-2 py-2 text-base leading-6 outline-none" placeholder="資料や過去の判断について質問する" /><div className="flex justify-end gap-1 border-t border-[var(--color-border-subtle)] pt-2"><Button type="button" variant="ghost" data-testid="knowledge-assist" onClick={() => setMessage((value) => value.trim() ? `${value.trim()}。関連する資料と過去の判断を比較してください。` : '関連する資料と過去の判断を比較してください。')} className="min-h-9 gap-1 px-2 text-xs"><Sparkles size={15} aria-hidden="true" />AI補完</Button><DropdownMenu><DropdownMenuTrigger asChild><Button type="button" variant="ghost" className="min-h-9 px-2 text-xs" aria-label={`モデル: ${modelLabel}`}>{modelLabel}</Button></DropdownMenuTrigger><DropdownMenuContent align="end" aria-label="AIモデルを選択"><DropdownMenuLabel>AIモデル</DropdownMenuLabel>{models.map((model) => <DropdownMenuItem key={model.logicalKey} onSelect={() => onModelChange?.(model.logicalKey)}>{model.displayName}{model.logicalKey === modelKey ? ' ✓' : ''}</DropdownMenuItem>)}</DropdownMenuContent></DropdownMenu><Button type="submit" aria-label="Knowledgeの質問を送信" className="min-h-9 min-w-9 px-2"><SendHorizontal size={17} aria-hidden="true" /><span className="sr-only">送信</span></Button></div></form>
  </section>;
}
