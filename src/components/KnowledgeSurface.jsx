import { useState } from 'react';
import { Badge } from './ui/Badge';
import { Button } from './ui/Button';
import { Card } from './ui/Card';
import { Field } from './ui/Field';

const stateLabel = { processing: '処理中', searchable: '検索可能', failed: '確認が必要' };

export function KnowledgeSurface({ fixture, onAddAsset = () => {}, onRemoveAsset = () => {}, onSend = () => {} }) {
  const [message, setMessage] = useState('');
  const [removeRequested, setRemoveRequested] = useState(false);
  const asset = fixture?.asset;
  const references = asset?.references?.filter((reference) => reference.status !== 'unavailable') ?? [];

  function submit(event) {
    event.preventDefault();
    const value = message.trim();
    if (!value) return;
    onSend(value);
    setMessage('');
  }

  if (!fixture || !asset || asset.state === 'deleted') {
    return <section aria-labelledby="knowledge-heading" className="mx-auto w-full max-w-6xl">
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[var(--color-text-muted)]">Knowledge</p>
      <h1 id="knowledge-heading" className="mt-3 text-3xl font-semibold tracking-tight">知識を育てる</h1>
      <p className="mt-2 text-sm text-[var(--color-text-muted)]">ファイル、対話、判断を同じ場所で振り返れます。</p>
      <Button className="mt-6" onClick={onAddAsset}>資料を追加</Button>
    </section>;
  }

  return <section aria-labelledby="knowledge-heading" className="mx-auto grid w-full max-w-6xl gap-6 pb-36">
    <header>
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[var(--color-text-muted)]">Knowledge</p>
      <h1 id="knowledge-heading" className="mt-3 text-3xl font-semibold tracking-tight">知識を育てる</h1>
      <p className="mt-2 max-w-2xl text-sm leading-6 text-[var(--color-text-muted)]">アップロードした資料と、プロジェクトの判断を横断して確認できます。</p>
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

    {removeRequested && <Card role="dialog" aria-modal="true" aria-labelledby="knowledge-delete-heading" className="border-red-200 p-6">
      <h2 id="knowledge-delete-heading" className="text-lg font-semibold">この資料を削除しますか？</h2>
      <p className="mt-2 text-sm leading-6 text-[var(--color-text-muted)]">原本、抽出内容、検索用の断片をこのspaceから削除します。この操作は元に戻せません。</p>
      <div className="mt-5 flex flex-wrap gap-3"><Button onClick={() => { onRemoveAsset(asset.id); setRemoveRequested(false); }}>削除を確定</Button><Button variant="secondary" onClick={() => setRemoveRequested(false)}>キャンセル</Button></div>
    </Card>}

    <form onSubmit={submit} className="sticky bottom-5 z-10 mx-auto w-full max-w-4xl rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface-raised)] p-3 shadow-lg">
      <Field label="Kadode AIに相談" className="sr-only"><span /></Field>
      <label htmlFor="knowledge-composer" className="sr-only">KnowledgeについてKadode AIに相談</label>
      <textarea id="knowledge-composer" value={message} onChange={(event) => setMessage(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} className="min-h-24 w-full resize-y bg-transparent px-2 py-2 text-base leading-6 outline-none" placeholder="資料や過去の判断について質問する" />
      <div className="flex items-center justify-between gap-3 border-t border-[var(--color-border-subtle)] pt-2"><span className="px-2 text-xs text-[var(--color-text-muted)]">Enterで送信 · Shift+Enterで改行</span><Button type="submit">送信</Button></div>
    </form>
  </section>;
}
