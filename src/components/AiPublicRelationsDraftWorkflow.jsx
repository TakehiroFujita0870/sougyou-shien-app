import { useMemo, useState } from 'react';

import { AI_PR_DRAFT_STATUSES, createAiPublicRelationsDraftRepository, validateDraftContent } from './AiPublicRelationsDraftRepository';

const STATUS_CLASSES = {
  [AI_PR_DRAFT_STATUSES.DRAFT]: 'bg-stone-100 text-stone-700',
  [AI_PR_DRAFT_STATUSES.REVISION_REQUESTED]: 'bg-amber-100 text-amber-900',
  [AI_PR_DRAFT_STATUSES.APPROVED]: 'bg-emerald-100 text-emerald-900',
  [AI_PR_DRAFT_STATUSES.REJECTED]: 'bg-red-100 text-red-800',
};

export function statusLabel(status) {
  if (status === AI_PR_DRAFT_STATUSES.REVISION_REQUESTED) return '修正依頼';
  if (status === AI_PR_DRAFT_STATUSES.APPROVED) return '承認';
  if (status === AI_PR_DRAFT_STATUSES.REJECTED) return '却下';
  return '下書き';
}

export function AiPublicRelationsDraftWorkflow({ repository: providedRepository }) {
  const repository = useMemo(() => providedRepository ?? createAiPublicRelationsDraftRepository(), [providedRepository]);
  const [draftContent, setDraftContent] = useState('');
  const [decisionNote, setDecisionNote] = useState('');
  const [selectedDraftId, setSelectedDraftId] = useState(null);
  const [drafts, setDrafts] = useState(() => repository.list());
  const [error, setError] = useState('');

  const selectedDraft = drafts.find((draft) => draft.id === selectedDraftId) ?? drafts[0] ?? null;

  function refresh(nextDraft) {
    setDrafts(repository.list());
    setSelectedDraftId(nextDraft.id);
    setDecisionNote('');
  }

  function saveDraft(event) {
    event.preventDefault();
    const errors = validateDraftContent(draftContent);
    if (errors.content) {
      setError(errors.content);
      return;
    }

    refresh(repository.create({ content: draftContent }));
    setDraftContent('');
    setError('');
  }

  function saveDecision(status) {
    if (!selectedDraft) return;
    try {
      const nextDraft = status === AI_PR_DRAFT_STATUSES.APPROVED
        ? repository.approve(selectedDraft.id, decisionNote)
        : status === AI_PR_DRAFT_STATUSES.REJECTED
          ? repository.reject(selectedDraft.id, decisionNote)
          : repository.requestRevision(selectedDraft.id, decisionNote);
      refresh(nextDraft);
      setError('');
    } catch (nextError) {
      setError(nextError.message);
    }
  }

  return (
    <section className="rounded-3xl border border-stone-200 bg-white p-6 shadow-sm" aria-labelledby="ai-pr-draft-heading">
      <p className="text-xs font-bold tracking-[0.16em] text-emerald-700">AI 広報部</p>
      <h2 id="ai-pr-draft-heading" className="mt-2 text-2xl font-bold">X投稿案の下書き・承認</h2>
      <p className="mt-2 text-sm leading-6 text-stone-600">外部公開やXへの投稿は行いません。個人情報・秘密情報を含む案は保存できません。</p>

      <form onSubmit={saveDraft} noValidate className="mt-6">
        <label htmlFor="ai-pr-draft-content" className="text-sm font-bold text-stone-800">投稿案</label>
        <textarea
          id="ai-pr-draft-content"
          value={draftContent}
          onChange={(event) => setDraftContent(event.target.value)}
          maxLength={280}
          rows={5}
          aria-invalid={Boolean(error)}
          aria-describedby="ai-pr-draft-help"
          className="mt-2 w-full resize-y rounded-xl border border-stone-300 px-4 py-3 outline-none focus:border-emerald-700 focus:ring-2 focus:ring-emerald-100"
          placeholder="開発から得た学びを、公開前の案として記録します。"
        />
        <div className="mt-2 flex items-center justify-between gap-3 text-xs text-stone-500">
          <p id="ai-pr-draft-help">280文字まで。連絡先、認証情報、APIキーは入力しないでください。</p>
          <span>{draftContent.length}/280</span>
        </div>
        <button type="submit" className="mt-4 rounded-full bg-emerald-800 px-5 py-2.5 text-sm font-bold text-white hover:bg-emerald-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-800">下書きを保存</button>
      </form>

      {error && <p role="alert" className="mt-4 rounded-xl bg-red-50 p-3 text-sm font-medium text-red-800">{error}</p>}

      <div className="mt-8 border-t border-stone-200 pt-6">
        <h3 className="text-lg font-bold">CEOの判断を保存</h3>
        {selectedDraft ? (
          <>
            <label htmlFor="ai-pr-decision-note" className="mt-4 block text-sm font-bold text-stone-800">判断メモ（任意）</label>
            <textarea id="ai-pr-decision-note" value={decisionNote} onChange={(event) => setDecisionNote(event.target.value)} rows={3} className="mt-2 w-full resize-y rounded-xl border border-stone-300 px-4 py-3 outline-none focus:border-emerald-700 focus:ring-2 focus:ring-emerald-100" placeholder="修正点や判断理由を記録します。" />
            <div className="mt-4 flex flex-wrap gap-3">
              <button type="button" onClick={() => saveDecision(AI_PR_DRAFT_STATUSES.REVISION_REQUESTED)} className="rounded-full border border-amber-700 px-4 py-2 text-sm font-bold text-amber-900 hover:bg-amber-50">修正を依頼</button>
              <button type="button" onClick={() => saveDecision(AI_PR_DRAFT_STATUSES.APPROVED)} className="rounded-full bg-emerald-800 px-4 py-2 text-sm font-bold text-white hover:bg-emerald-900">承認する</button>
              <button type="button" onClick={() => saveDecision(AI_PR_DRAFT_STATUSES.REJECTED)} className="rounded-full border border-red-700 px-4 py-2 text-sm font-bold text-red-800 hover:bg-red-50">却下する</button>
            </div>
          </>
        ) : <p className="mt-3 text-sm text-stone-600">下書きを保存すると、ここで判断を記録できます。</p>}
      </div>

      <ol className="mt-8 grid gap-3" aria-label="保存済み下書き">
        {drafts.map((draft) => (
          <li key={draft.id}>
            <button type="button" onClick={() => setSelectedDraftId(draft.id)} className="w-full rounded-2xl border border-stone-200 p-4 text-left hover:border-emerald-400 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-800">
              <span className={`rounded-full px-2.5 py-1 text-xs font-bold ${STATUS_CLASSES[draft.status]}`}>{statusLabel(draft.status)}</span>
              <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-stone-800">{draft.content}</p>
              {draft.decisionNote && <p className="mt-2 text-xs leading-5 text-stone-500">判断メモ: {draft.decisionNote}</p>}
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}
