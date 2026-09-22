import { useId, useMemo } from 'react';
import { Badge } from './ui/Badge';
import { Card } from './ui/Card';
import FounderGraphReportDiff from './FounderGraphReportDiff';

const SAFE_RUN_FIELDS = ['id', 'status', 'model_snapshot', 'created_at', 'finished_at'];
const SAFE_CAMPAIGN_FIELDS = ['id', 'purpose', 'status', 'trial_budget', 'run_count'];
const STATES = new Set(['loading', 'unavailable', 'error', 'empty']);
const STATE_MESSAGES = {
  loading: 'Campaign比較を読み込んでいます。',
  unavailable: 'Campaign比較は現在利用できません。',
  error: 'Campaign比較の読み込みに失敗しました。',
};

function text(value) {
  return typeof value === 'string' ? value.trim() : '';
}

function scalar(value) {
  if (typeof value === 'string') return value.trim();
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return '';
}

function safeObject(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

function projectRun(value) {
  const source = safeObject(value);
  const projected = {};
  SAFE_RUN_FIELDS.forEach((key) => {
    const valueText = scalar(source[key]);
    if (valueText) projected[key] = valueText;
  });
  return projected.id ? projected : null;
}

function projectCampaign(value) {
  const source = safeObject(value);
  const projected = {};
  SAFE_CAMPAIGN_FIELDS.forEach((key) => {
    const valueText = scalar(source[key]);
    if (valueText) projected[key] = valueText;
  });
  return projected.id ? projected : null;
}

function normalizeRuns(value) {
  if (!Array.isArray(value)) return [];
  const seen = new Set();
  return value.map(projectRun).filter((run) => {
    if (!run || seen.has(run.id)) return false;
    seen.add(run.id);
    return true;
  });
}

function normalizeState(value) {
  return STATES.has(value) ? value : 'ready';
}

export function projectFounderGraphCampaignCompare({ campaign, runs, previousReport, currentReport } = {}) {
  const safeCampaign = projectCampaign(campaign);
  const safeRuns = normalizeRuns(runs);
  return {
    campaign: safeCampaign,
    runs: safeRuns,
    previousReport: previousReport && typeof previousReport === 'object' ? previousReport : null,
    currentReport: currentReport && typeof currentReport === 'object' ? currentReport : null,
  };
}

export function FounderGraphCampaignCompare({ campaign, runs, previousReport, currentReport, state, status, initialSection = 0, exportState, exportStatus, onExportRequest }) {
  const headingId = useId();
  const model = useMemo(
    () => projectFounderGraphCampaignCompare({ campaign, runs, previousReport, currentReport }),
    [campaign, runs, previousReport, currentReport],
  );
  const resolvedState = normalizeState(state ?? status);
  const hasReports = Boolean(model.previousReport || model.currentReport);
  const isEmpty = resolvedState === 'empty' || (resolvedState === 'ready' && (!model.campaign || model.runs.length === 0 || !hasReports));
  const message = STATE_MESSAGES[resolvedState];

  return (
    <section
      aria-labelledby={`${headingId}-title`}
      aria-busy={resolvedState === 'loading'}
      data-founder-graph-campaign-compare="true"
      data-founder-graph-campaign-state={resolvedState}
      data-read-only="true"
      className="mx-auto grid w-full max-w-6xl gap-5"
    >
      <header>
        <p className="text-xs font-semibold uppercase tracking-[.18em] text-[var(--color-text-muted)]">Campaign / Run comparison</p>
        <h1 id={`${headingId}-title`} className="mt-2 text-3xl font-semibold tracking-tight">調査Campaign比較</h1>
        <p className="mt-2 text-sm text-[var(--color-text-muted)]">同じCampaignに属する試行と8章ReportVersionを読み取り専用で比較します。</p>
      </header>

      {message && (
        <p role={resolvedState === 'error' ? 'alert' : 'status'} aria-live={resolvedState === 'error' ? 'assertive' : 'polite'} data-founder-graph-campaign-state-message={resolvedState} className="rounded-xl border border-[var(--color-border-subtle)] bg-[var(--color-muted)] px-4 py-3 text-sm">
          {message}
        </p>
      )}

      {isEmpty && (
        <p role="status" aria-live="polite" data-founder-graph-campaign-state-message="empty" className="rounded-xl border border-[var(--color-border-subtle)] bg-[var(--color-muted)] px-4 py-3 text-sm">
          比較できるCampaign、Run、ReportVersionがありません。
        </p>
      )}

      {resolvedState === 'ready' && !isEmpty && (
        <>
          <Card data-founder-graph-campaign-metadata="true" className="p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[.16em] text-[var(--color-text-muted)]">Campaign</p>
                <h2 className="mt-2 text-xl font-semibold">{model.campaign.purpose || model.campaign.id}</h2>
              </div>
              {model.campaign.status && <Badge variant="outline">{model.campaign.status}</Badge>}
            </div>
            <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-3">
              <div><dt className="font-semibold text-[var(--color-text-muted)]">Campaign ID</dt><dd className="mt-1 break-words">{model.campaign.id}</dd></div>
              <div><dt className="font-semibold text-[var(--color-text-muted)]">試行数</dt><dd className="mt-1">{model.runs.length}{model.campaign.trial_budget ? ` / ${model.campaign.trial_budget}` : ''}</dd></div>
              <div><dt className="font-semibold text-[var(--color-text-muted)]">Report比較</dt><dd className="mt-1">{model.previousReport && model.currentReport ? '前版 / 現版' : '片側のみ'}</dd></div>
            </dl>
          </Card>

          <Card data-founder-graph-campaign-runs="true" className="p-5">
            <h2 className="text-lg font-semibold">ResearchRun</h2>
            <ul className="mt-3 grid gap-2 text-sm" aria-label="ResearchRun一覧">
              {model.runs.map((run) => <li key={run.id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-[var(--color-border-subtle)] px-3 py-2"><span className="break-words">{run.id}</span>{run.status && <Badge variant="outline">{run.status}</Badge>}</li>)}
            </ul>
          </Card>

          <FounderGraphReportDiff
            previousReport={model.previousReport}
            currentReport={model.currentReport}
            initialSection={initialSection}
            exportState={exportState}
            exportStatus={exportStatus}
            onExportRequest={onExportRequest}
          />
        </>
      )}
    </section>
  );
}

export default FounderGraphCampaignCompare;
