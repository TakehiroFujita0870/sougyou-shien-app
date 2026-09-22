import { useId, useMemo, useRef, useState } from 'react';
import { Badge } from './ui/Badge';
import { Card } from './ui/Card';
import FounderGraphReportDiff from './FounderGraphReportDiff';

export const FOUNDER_GRAPH_CATEGORIES = [
  { key: 'ideas', kind: 'idea', label: 'Ideas' },
  { key: 'assets', kind: 'asset', label: 'Assets' },
  { key: 'sources', kind: 'source', label: 'Sources' },
  { key: 'people', kind: 'person', label: 'People' },
];

export const FOUNDER_GRAPH_REPORT_CATEGORY = Object.freeze({
  key: 'reports',
  kind: 'report',
  label: 'Reports',
});

const CATEGORY_BY_KIND = Object.fromEntries(FOUNDER_GRAPH_CATEGORIES.map((category) => [category.kind, category]));
const TOP_LEVEL_SAFE_FIELDS = ['locator', 'content_hash', 'source_id'];
const SAFE_FIELDS_BY_KIND = {
  idea: ['summary', 'description', 'tags', 'status', 'revision', 'supersedes_id'],
  asset: ['name', 'kind', 'description', 'status'],
  source: ['title', 'kind', 'locator', 'current_revision_id', 'revision', 'status'],
  person: ['name', 'description', 'status'],
};
const SAFE_FIELD_LABELS = {
  summary: 'Summary',
  description: 'Description',
  tags: 'Tags',
  revision: 'Revision',
  supersedes_id: 'Supersedes',
  name: 'Name',
  kind: 'Kind detail',
  locator: 'Locator',
  current_revision_id: 'Current revision',
  source_id: 'Source',
  content_hash: 'Content hash',
};

const TRANSIENT_STATE_MESSAGES = {
  loading: 'Founder Graphを読み込んでいます。',
  unavailable: 'Founder Graphは現在利用できません。',
  error: 'Founder Graphの読み込みに失敗しました。',
};

function asText(value) {
  return typeof value === 'string' ? value.trim() : '';
}

function displayValue(value) {
  if (typeof value === 'string') return value.trim();
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value)) {
    const values = value
      .filter((item) => typeof item === 'string' || typeof item === 'number' || typeof item === 'boolean')
      .map((item) => String(item).trim())
      .filter(Boolean);
    return values.join(' / ');
  }
  return '';
}

function safeRelationPath(value) {
  if (!Array.isArray(value)) return [];
  return value.filter((item) => typeof item === 'string' && item.trim()).map((item) => item.trim());
}

function safeFieldsForResult(kind, fields, result) {
  const sourceFields = fields && typeof fields === 'object' && !Array.isArray(fields) ? fields : {};
  const safeFields = {};
  for (const key of SAFE_FIELDS_BY_KIND[kind]) {
    const value = displayValue(sourceFields[key]);
    if (value) safeFields[key] = value;
  }
  for (const key of TOP_LEVEL_SAFE_FIELDS) {
    const value = displayValue(result[key] ?? sourceFields[key]);
    if (value) safeFields[key] = value;
  }
  return safeFields;
}

/**
 * Keep the UI input at the read-MCP projection boundary.
 * Unknown keys and local-only/raw content are deliberately not copied.
 */
export function projectFounderGraphResult(result) {
  if (!result || typeof result !== 'object' || Array.isArray(result)) return null;
  const kind = asText(result.kind);
  if (!CATEGORY_BY_KIND[kind]) return null;
  const id = asText(result.id);
  if (!id) return null;

  const fields = result.fields && typeof result.fields === 'object' && !Array.isArray(result.fields) ? result.fields : {};
  const egressPolicy = asText(result.egress_policy) || asText(fields.egress_policy);
  if (egressPolicy && egressPolicy !== 'shareable') return null;

  const status = asText(result.status) || displayValue(fields.status);
  return {
    id,
    kind,
    title: asText(result.title) || id,
    snippet: asText(result.snippet),
    status: status || 'unknown',
    relationPath: safeRelationPath(result.relation_path),
    fields: safeFieldsForResult(kind, fields, result),
  };
}

export function projectFounderGraphResults(results) {
  if (!Array.isArray(results)) return [];
  const seen = new Set();
  return results
    .map(projectFounderGraphResult)
    .filter((result) => {
      if (!result || seen.has(result.id)) return false;
      seen.add(result.id);
      return true;
    });
}

function normalizeState(value) {
  return ['loading', 'unavailable', 'error', 'empty'].includes(value) ? value : 'ready';
}

/**
 * Normalize the optional report-diff input without forwarding arbitrary keys
 * from the parent surface into the report component.
 *
 * Both the report component's canonical names and its before/after aliases are
 * accepted so the surface can be composed from either read projection shape.
 */
function normalizeReportConfig(reports) {
  if (Array.isArray(reports)) {
    const previousReport = reports[0] ?? null;
    const currentReport = reports[1] ?? null;
    return previousReport || currentReport ? { previousReport, currentReport } : null;
  }
  if (!reports || typeof reports !== 'object') return null;

  const previousReport = reports.previousReport ?? reports.before ?? reports.previous ?? null;
  const currentReport = reports.currentReport ?? reports.after ?? reports.current ?? null;
  if (!previousReport && !currentReport) return null;

  return {
    previousReport,
    currentReport,
    state: reports.state,
    status: reports.status,
    exportState: reports.exportState,
    exportStatus: reports.exportStatus,
    onExportRequest: typeof reports.onExportRequest === 'function' ? reports.onExportRequest : undefined,
    initialSection: reports.initialSection,
  };
}

function focusTab(tabRefs, index) {
  if (typeof requestAnimationFrame !== 'function') {
    tabRefs.current[index]?.focus();
    return;
  }
  requestAnimationFrame(() => tabRefs.current[index]?.focus());
}

export function FounderGraphSurface({ results, fixture, state, status, initialCategory = 'ideas', reports }) {
  const headingId = useId();
  const tabRefs = useRef([]);
  const reportConfig = useMemo(() => normalizeReportConfig(reports), [reports]);
  const categoryDefinitions = useMemo(
    () => reportConfig ? [...FOUNDER_GRAPH_CATEGORIES, FOUNDER_GRAPH_REPORT_CATEGORY] : FOUNDER_GRAPH_CATEGORIES,
    [reportConfig],
  );
  const categoryKeys = useMemo(() => new Set(categoryDefinitions.map((category) => category.key)), [categoryDefinitions]);
  const initialKey = categoryKeys.has(initialCategory) ? initialCategory : 'ideas';
  const [activeCategory, setActiveCategory] = useState(initialKey);
  const [selectedId, setSelectedId] = useState(null);
  const safeResults = useMemo(
    () => projectFounderGraphResults(results ?? fixture?.results ?? []),
    [fixture?.results, results],
  );
  const resolvedState = normalizeState(state ?? status ?? fixture?.state ?? fixture?.status);
  const activeCategoryKey = categoryKeys.has(activeCategory) ? activeCategory : 'ideas';
  const activeIndex = categoryDefinitions.findIndex((category) => category.key === activeCategoryKey);
  const activeDefinition = categoryDefinitions[activeIndex];
  const activeResults = resolvedState === 'ready' && activeDefinition.kind !== FOUNDER_GRAPH_REPORT_CATEGORY.kind
    ? safeResults.filter((result) => result.kind === activeDefinition.kind)
    : [];
  const selectedNode = activeResults.find((result) => result.id === selectedId) ?? null;

  function selectCategory(index) {
    const nextCategory = categoryDefinitions[index];
    if (!nextCategory) return;
    setActiveCategory(nextCategory.key);
    setSelectedId(null);
    focusTab(tabRefs, index);
  }

  function handleTabKeyDown(event, index) {
    let nextIndex = index;
    if (event.key === 'ArrowRight') nextIndex = (index + 1) % categoryDefinitions.length;
    else if (event.key === 'ArrowLeft') nextIndex = (index - 1 + categoryDefinitions.length) % categoryDefinitions.length;
    else if (event.key === 'Home') nextIndex = 0;
    else if (event.key === 'End') nextIndex = categoryDefinitions.length - 1;
    else return;
    event.preventDefault();
    selectCategory(nextIndex);
  }

  const emptyState = resolvedState === 'empty' || (resolvedState === 'ready' && activeResults.length === 0);
  const stateMessage = TRANSIENT_STATE_MESSAGES[resolvedState];

  return (
    <section
      aria-labelledby={`${headingId}-title`}
      aria-busy={resolvedState === 'loading'}
      data-founder-graph-surface="true"
      data-founder-graph-state={resolvedState}
      data-read-only="true"
      className="mx-auto grid w-full max-w-6xl gap-5"
    >
      <header>
        <p className="text-xs font-semibold uppercase tracking-[.18em] text-[var(--color-text-muted)]">Founder Graph</p>
        <h1 id={`${headingId}-title`} className="mt-2 text-3xl font-semibold tracking-tight">{categoryDefinitions.map((category) => category.label).join('・')}</h1>
        <p className="mt-2 text-sm text-[var(--color-text-muted)]">ローカルGraphの安全な読み取り結果を確認します。</p>
      </header>

      <div role="tablist" aria-label="Founder Graphカテゴリ" className="flex gap-1 overflow-x-auto border-b border-[var(--color-border-subtle)] pb-px">
        {categoryDefinitions.map((category, index) => (
          <button
            key={category.key}
            ref={(node) => { tabRefs.current[index] = node; }}
            id={`${headingId}-tab-${category.key}`}
            type="button"
            role="tab"
            data-founder-graph-category-tab="true"
            aria-selected={activeCategoryKey === category.key}
            aria-controls={`${headingId}-panel`}
            tabIndex={activeCategoryKey === category.key ? 0 : -1}
            onClick={() => selectCategory(index)}
            onKeyDown={(event) => handleTabKeyDown(event, index)}
            className={`shrink-0 border-b-2 px-3 py-2 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring)] ${activeCategoryKey === category.key ? 'border-[var(--color-primary)] text-[var(--color-text)]' : 'border-transparent text-[var(--color-text-muted)] hover:text-[var(--color-text)]'}`}
          >
            {category.label}
          </button>
        ))}
      </div>

      {stateMessage && (
        <p
          role={resolvedState === 'error' ? 'alert' : 'status'}
          aria-live={resolvedState === 'error' ? 'assertive' : 'polite'}
          data-founder-graph-state-message={resolvedState}
          className="rounded-xl border border-[var(--color-border-subtle)] bg-[var(--color-muted)] px-4 py-3 text-sm"
        >
          {stateMessage}
        </p>
      )}

      <div id={`${headingId}-panel`} role="tabpanel" aria-labelledby={`${headingId}-tab-${activeCategoryKey}`} className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        {activeCategoryKey === FOUNDER_GRAPH_REPORT_CATEGORY.key && reportConfig ? (
          <FounderGraphReportDiff {...reportConfig} />
        ) : (
          <>
            {emptyState && (
              <p role="status" aria-live="polite" data-founder-graph-state-message="empty" className="rounded-xl border border-[var(--color-border-subtle)] bg-[var(--color-muted)] px-4 py-3 text-sm">
                このカテゴリにはノードがありません。
              </p>
            )}

            {resolvedState === 'ready' && activeResults.length > 0 && (
              <>
                <div>
                  <h2 className="text-sm font-semibold text-[var(--color-text-muted)]">{activeDefinition.label}</h2>
                  <ul aria-label={`${activeDefinition.label}の一覧`} className="mt-3 grid gap-3">
                    {activeResults.map((result) => (
                      <li key={result.id}>
                        <button
                          type="button"
                          data-founder-graph-card="true"
                          aria-pressed={selectedId === result.id}
                          onClick={() => setSelectedId(result.id)}
                          className="block w-full rounded-2xl text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring)]"
                        >
                          <Card className={`h-full p-4 transition-colors ${selectedId === result.id ? 'border-[var(--color-primary)] ring-1 ring-[var(--color-primary)]' : 'hover:border-[var(--color-primary)]'}`}>
                            <div className="flex items-start justify-between gap-3">
                              <h3 className="font-semibold">{result.title}</h3>
                              <Badge variant="outline">{result.status}</Badge>
                            </div>
                            <p className="mt-2 text-sm leading-6 text-[var(--color-text-muted)]">{result.snippet || 'Snippetはありません。'}</p>
                          </Card>
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>

                {selectedNode && (
                  <Card data-founder-graph-detail="true" aria-labelledby={`${headingId}-detail-title`} className="p-5">
                    <p className="text-xs font-semibold uppercase tracking-[.16em] text-[var(--color-text-muted)]">Selected node</p>
                    <h2 id={`${headingId}-detail-title`} className="mt-2 text-xl font-semibold">{selectedNode.title}</h2>
                    <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
                      <div><dt className="font-semibold text-[var(--color-text-muted)]">Kind</dt><dd className="mt-1">{selectedNode.kind}</dd></div>
                      <div><dt className="font-semibold text-[var(--color-text-muted)]">Status</dt><dd className="mt-1">{selectedNode.status}</dd></div>
                      <div className="sm:col-span-2"><dt className="font-semibold text-[var(--color-text-muted)]">Snippet</dt><dd className="mt-1 leading-6">{selectedNode.snippet || 'Snippetはありません。'}</dd></div>
                      <div className="sm:col-span-2"><dt className="font-semibold text-[var(--color-text-muted)]">Relation path</dt><dd className="mt-1 break-words leading-6">{selectedNode.relationPath.length ? selectedNode.relationPath.join(' → ') : 'なし'}</dd></div>
                    </dl>
                    {Object.keys(selectedNode.fields).length > 0 && (
                      <dl className="mt-5 grid gap-3 border-t border-[var(--color-border-subtle)] pt-4 text-sm sm:grid-cols-2">
                        {Object.entries(selectedNode.fields).map(([key, value]) => (
                          <div key={key} data-founder-graph-safe-field={key}>
                            <dt className="font-semibold text-[var(--color-text-muted)]">{SAFE_FIELD_LABELS[key] ?? key}</dt>
                            <dd className="mt-1 break-words">{value}</dd>
                          </div>
                        ))}
                      </dl>
                    )}
                  </Card>
                )}
              </>
            )}
          </>
        )}
      </div>
    </section>
  );
}

export default FounderGraphSurface;
