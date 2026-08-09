import { useEffect, useRef, useState } from 'react';
import { SendHorizontal, Sparkles } from 'lucide-react';
import { Badge } from './ui/Badge';
import { Button } from './ui/Button';
import { Card } from './ui/Card';
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogTitle } from './ui/Dialog';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuTrigger } from './ui/DropdownMenu';
import { createKnowledgeMetadataRepository } from './knowledgeMetadataRepository';

const stateLabel = { processing: '処理中', searchable: '検索可能', failed: '確認が必要' };

function assetMetadata(asset) {
  return { id: asset.id, name: asset.name, version: asset.version, state: asset.state, extractedTextState: asset.state === 'searchable' ? 'ready' : 'pending', indexState: asset.state === 'searchable' ? 'ready' : 'pending' };
}

export function KnowledgeSurface({ fixture, repository, ownerId = 'admin-demo-owner', spaceId = 'admin-demo-space', onAddAsset = () => {}, onRemoveAsset = () => {}, onSend = () => {}, modelKey = 'gpt-5.6-terra', models = [], onModelChange }) {
  const [message, setMessage] = useState('');
  const [removeRequested, setRemoveRequested] = useState(false);
  const [deleted, setDeleted] = useState(false);
  const [persistenceError, setPersistenceError] = useState(false);
  const repositoryRef = useRef(repository ?? createKnowledgeMetadataRepository({ ownerId, spaceId }));
  const asset = fixture?.asset;
  const references = asset?.references?.filter((reference) => reference.status !== 'unavailable') ?? [];
  const modelLabel = models.find((model) => model.logicalKey === modelKey)?.displayName ?? 'GPT-5.6 Terra';

  useEffect(() => {
    let active = true;
    const localRepository = repositoryRef.current;
    localRepository.load().then(() => {
      if (!active) return;
      setDeleted(localRepository.find(asset?.id)?.state === 'deleted');
      setPersistenceError(Boolean(localRepository.getLastError?.()));
    }).catch(() => {
      if (active) setPersistenceError(true);
    });
    return () => { active = false; };
  }, [asset?.id]);

  function submit(event) {
    event.preventDefault();
    const value = message.trim();
    if (!value) return;
    onSend(value);
    setMessage('');
  }

  async function confirmRemoval() {
    if (!asset) return;
    try {
      const deletedMetadata = await repositoryRef.current.delete(asset.id, assetMetadata(asset));
      if (!deletedMetadata) throw new Error('Metadata could not be deleted');
      onRemoveAsset(asset.id);
      setDeleted(true);
      setPersistenceError(false);
      setRemoveRequested(false);
    } catch {
      setPersistenceError(true);
      setRemoveRequested(false);
    }
  }

  if (!fixture || !asset || asset.state === 'deleted' || deleted) {
    return <section aria-labelledby="knowledge-heading" className="mx-auto w-full max-w-6xl">
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[var(--color-text-muted)]">Knowledge</p>
      <h1 id="knowledge-heading" className="mt-3 text-3xl font-semibold tracking-tight">知識を育てる</h1>
      <p className="mt-2 text-sm text-[var(--color-text-muted)]">ファイル、対話、判断を同じ場所で振り返れます。</p>
      {persistenceError && <p role="status" className="mt-4 text-sm text-[var(--color-destructive)]">保存状態を確認できません。ページを再読み込みしてから、もう一度お試しください。</p>}
      <Button className="mt-6" onClick={onAddAsset}>資料を追加</Button>
    </section>;
  }

  return <section aria-labelledby="knowledge-heading" className="mx-auto grid w-full max-w-6xl gap-6 pb-36">
    <header>
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[var(--color-text-muted)]">Knowledge</p>
      <h1 id="knowledge-heading" className="mt-3 text-3xl font-semibold tracking-tight">知識を育てる</h1>
      <p className="mt-2 max-w-2xl text-sm leading-6 text-[var(--color-text-muted)]">アップロードした資料と、プロジェクトの判断を横断して確認できます。</p>
      {persistenceError && <p role="status" className="mt-3 text-sm text-[var(--color-destructive)]">保存状態を確認できません。削除は反映されていません。ページを再読み込みしてから、もう一度お試しください。</p>}
    </header>

    <div className="grid gap-6 lg:grid-cols-[minmax(0,1.15fr)_minmax(18rem,.85fr)]">
      <Card className="p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2"><h2 className="truncate text-lg font-semibold">{asset.name}</h2><Badge variant="outline">{stateLabel[asset.state] ?? asset.state}</Badge></div>
            <p className="mt-2 text-sm text-[var(--color-text-muted)]">バージョン {asset.version} · このspaceで参照可能</p>
          </div>
          <Button variant="secondary" onClick={() => setRemoveRequested(true)}>削除</Button>
        </div>
        <div className="mt-6 border-t border-[var(--color-border-subtle)] pt-5">
          <h3 className="text-sm font-semibold">参照元</h3>
          <ul aria-label="利用可能な出典" className="mt-3 grid gap-2 text-sm text-[var(--color-text-muted)]">
            {references.map((reference) => <li key={`${reference.kind}-${reference.sourceId}-${reference.locator}`} className="rounded-lg bg-[var(--color-muted)] px-3 py-2"><span className="font-medium text-[var(--color-text)]">{reference.kind}</span> · {reference.locator}</li>)}
          </ul>
        </div>
      </Card>

      <Card className="p-6">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[var(--color-text-muted)]">Project context</p>
        <h2 className="mt-3 text-lg font-semibold">{fixture.project.name}</h2>
        <p className="mt-2 text-sm leading-6 text-[var(--color-text-muted)]">{fixture.project.summary}</p>
        <dl className="mt-6 grid gap-4 border-t border-[var(--color-border-subtle)] pt-5 text-sm">
          <div><dt className="font-medium text-[var(--color-text-muted)]">背景</dt><dd className="mt-1">{fixture.decision.background}</dd></div>
          <div><dt className="font-medium text-[var(--color-text-muted)]">判断</dt><dd className="mt-1">{fixture.decision.judgement}</dd></div>
          <div><dt className="font-medium text-[var(--color-text-muted)]">理由</dt><dd className="mt-1">{fixture.decision.reason}</dd></div>
        </dl>
      </Card>
    </div>

    <Dialog open={removeRequested} onOpenChange={setRemoveRequested}>
      <DialogContent>
        <DialogTitle className="text-lg font-semibold">この資料を削除しますか？</DialogTitle>
        <DialogDescription className="mt-2 text-sm leading-6 text-[var(--color-text-muted)]">原本、抽出内容、検索用の断片をこのspaceから削除します。この操作は元に戻せません。</DialogDescription>
        <div className="mt-5 flex flex-wrap gap-3"><Button onClick={confirmRemoval}>削除を確定</Button><DialogClose asChild><Button variant="secondary">キャンセル</Button></DialogClose></div>
      </DialogContent>
    </Dialog>

    <form onSubmit={submit} className="sticky bottom-5 z-10 mx-auto w-full max-w-4xl rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-3 shadow-lg">
      <label htmlFor="knowledge-composer" className="sr-only">KnowledgeについてKadode AIに相談</label>
      <textarea id="knowledge-composer" value={message} onChange={(event) => setMessage(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} className="min-h-24 w-full resize-y bg-transparent px-2 py-2 text-base leading-6 outline-none" placeholder="資料や過去の判断について質問する" />
      <div className="flex justify-end gap-1 border-t border-[var(--color-border-subtle)] pt-2">
        <Button type="button" variant="ghost" data-testid="knowledge-assist" onClick={() => setMessage((value) => value.trim() ? `${value.trim()}。関連する資料と過去の判断を比較してください。` : '関連する資料と過去の判断を比較してください。')} className="min-h-9 gap-1 px-2 text-xs"><Sparkles size={15} aria-hidden="true" />AI補完</Button>
        <DropdownMenu><DropdownMenuTrigger asChild><Button type="button" variant="ghost" className="min-h-9 px-2 text-xs" aria-label={`モデル: ${modelLabel}`}>{modelLabel}</Button></DropdownMenuTrigger><DropdownMenuContent align="end" aria-label="AIモデルを選択"><DropdownMenuLabel>AIモデル</DropdownMenuLabel>{models.map((model) => <DropdownMenuItem key={model.logicalKey} onSelect={() => onModelChange?.(model.logicalKey)}>{model.displayName}{model.logicalKey === modelKey ? ' ✓' : ''}</DropdownMenuItem>)}</DropdownMenuContent></DropdownMenu>
        <Button type="submit" aria-label="Knowledgeの質問を送信" className="min-h-9 min-w-9 px-2"><SendHorizontal size={17} aria-hidden="true" /><span className="sr-only">送信</span></Button>
      </div>
    </form>
  </section>;
}
