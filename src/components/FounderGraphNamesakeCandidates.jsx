import { useMemo, useState } from 'react';
import { Card } from './ui/Card';

function asText(value) {
  return typeof value === 'string' ? value.trim() : '';
}

function safePersonIds(value) {
  if (!Array.isArray(value) || value.length !== 2) return null;
  const personIds = value.map(asText);
  return personIds.every(Boolean) && personIds[0] !== personIds[1] ? personIds : null;
}

function safeReasons(value) {
  if (!Array.isArray(value)) return [];
  const allowed = new Set(['same_name', 'same_email', 'same_phone']);
  return [...new Set(value.map(asText).filter((reason) => allowed.has(reason)))];
}

function safeConfidence(value) {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1 ? value : null;
}

/**
 * Project candidates at the UI boundary. The merge review must never display
 * contact values or retain arbitrary candidate properties.
 */
export function projectNamesakeCandidates(candidates) {
  if (!Array.isArray(candidates)) return [];
  const seen = new Set();
  return candidates.flatMap((candidate) => {
    if (!candidate || typeof candidate !== 'object' || Array.isArray(candidate)) return [];
    const personIds = safePersonIds(candidate.person_ids);
    const reasons = safeReasons(candidate.reasons);
    const confidence = safeConfidence(candidate.confidence);
    if (!personIds || !reasons.length || confidence === null || candidate.status !== 'proposed') return [];
    const key = personIds.slice().sort().join(':');
    if (seen.has(key)) return [];
    seen.add(key);
    return [{ personIds, reasons, confidence }];
  });
}

function NamesakeCandidateCard({ candidate, onConfirm }) {
  const [winnerId, setWinnerId] = useState('');
  const [evidenceId, setEvidenceId] = useState('');
  const [error, setError] = useState('');
  const [firstPersonId, secondPersonId] = candidate.personIds;

  function submitConfirmation(event) {
    event.preventDefault();
    if (typeof onConfirm !== 'function') {
      setError('この画面では統合を依頼できません。');
      return;
    }
    const normalizedEvidenceId = evidenceId.trim();
    if (!winnerId || !normalizedEvidenceId) {
      setError('勝者と根拠IDを選択してください。');
      return;
    }
    const loserId = winnerId === firstPersonId ? secondPersonId : firstPersonId;
    setError('');
    onConfirm({
      winner_person_id: winnerId,
      loser_person_id: loserId,
      confirmation: 'confirmed',
      evidence_ids: [normalizedEvidenceId],
    });
  }

  return (
    <Card className="p-4">
      <form onSubmit={submitConfirmation}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="font-semibold">同一人物の候補</h3>
            <p className="mt-1 text-sm text-[var(--color-text-muted)]">候補理由: {candidate.reasons.join(' / ')}・確度: {candidate.confidence}</p>
          </div>
          <span className="rounded-full border border-[var(--color-border-subtle)] px-2 py-1 text-xs font-medium">提案中</span>
        </div>

        <fieldset className="mt-4 grid gap-2">
          <legend className="text-sm font-semibold">残す人物を選択</legend>
          {candidate.personIds.map((personId) => (
            <label key={personId} className="flex items-center gap-2 text-sm">
              <input
                type="radio"
                name={`namesake-winner-${firstPersonId}-${secondPersonId}`}
                value={personId}
                checked={winnerId === personId}
                onChange={(event) => setWinnerId(event.target.value)}
              />
              {personId}
            </label>
          ))}
        </fieldset>

        <label className="mt-4 grid gap-1 text-sm font-semibold">
          統合を裏付ける根拠ID
          <input
            data-founder-graph-merge-evidence-id="true"
            type="text"
            value={evidenceId}
            onChange={(event) => setEvidenceId(event.target.value)}
            className="rounded-lg border border-[var(--color-border-subtle)] bg-transparent px-3 py-2 font-normal"
          />
        </label>
        {error && <p data-founder-graph-namesake-merge-error="true" role="alert" className="mt-3 text-sm text-[var(--color-danger)]">{error}</p>}
        <p className="mt-3 text-sm text-[var(--color-text-muted)]">確定を押すまで、保存済みの人物は変更されません。</p>
        <button data-founder-graph-confirm-namesake-merge="true" type="submit" disabled={typeof onConfirm !== 'function'} className="mt-3 rounded-lg border border-[var(--color-border-subtle)] px-3 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring)]">
          確定して統合を依頼
        </button>
      </form>
    </Card>
  );
}

/** A callback-only confirmation surface; it deliberately has no write path. */
export function FounderGraphNamesakeCandidates({ candidates, onConfirm }) {
  const safeCandidates = useMemo(() => projectNamesakeCandidates(candidates), [candidates]);
  if (!safeCandidates.length) return null;

  return (
    <section data-founder-graph-namesake-candidates="true" aria-label="同姓同名の統合候補" className="grid gap-3">
      <div>
        <h2 className="text-lg font-semibold">同姓同名の統合候補</h2>
        <p className="mt-1 text-sm text-[var(--color-text-muted)]">候補は提案中です。連絡先の値は表示せず、明示確認だけを依頼します。</p>
      </div>
      {safeCandidates.map((candidate) => (
        <NamesakeCandidateCard key={candidate.personIds.join(':')} candidate={candidate} onConfirm={onConfirm} />
      ))}
    </section>
  );
}

export default FounderGraphNamesakeCandidates;
