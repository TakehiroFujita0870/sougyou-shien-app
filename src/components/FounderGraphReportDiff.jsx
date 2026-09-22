import { useId, useMemo, useRef, useState } from 'react';
import { Badge } from './ui/Badge';
import { Button } from './ui/Button';
import { Card } from './ui/Card';

export const FOUNDER_GRAPH_REPORT_CHAPTERS = Object.freeze([
  { id: 0, title: 'エグゼクティブサマリー' },
  { id: 1, title: 'ビジネスモデル' },
  { id: 2, title: '顧客とマーケットサイズ' },
  { id: 3, title: '収益モデル' },
  { id: 4, title: '競争優位性' },
  { id: 5, title: '実現可能性' },
  { id: 6, title: 'リスク・撤退ライン' },
  { id: 7, title: 'リスクミニマムなロードマップ' },
]);

const REPORT_CHAPTER_IDS = new Set(FOUNDER_GRAPH_REPORT_CHAPTERS.map((chapter) => chapter.id));

export const REPORT_CHANGE_STATUSES = Object.freeze({
  added: { label: '追加', description: '現版に追加された章' },
  changed: { label: '変更', description: '前版から内容が変わった章' },
  unchanged: { label: '変更なし', description: '前版から内容が変わっていない章' },
  removed: { label: '削除', description: '現版で内容がなくなった章' },
});

export const FOUNDER_GRAPH_EXPORT_FORMATS = Object.freeze(['json', 'markdown']);
export const FOUNDER_GRAPH_EXPORT_SCOPE = 'report_versions';
export const FOUNDER_GRAPH_EXPORT_PROJECTION = 'shareable';

const TRANSIENT_STATE_MESSAGES = {
  loading: 'レポート差分を読み込んでいます。',
  unavailable: 'レポート差分は現在利用できません。',
  error: 'レポート差分の読み込みに失敗しました。',
};

const EXPORT_STATE_MESSAGES = {
  loading: 'exportを準備しています。',
  unavailable: 'exportは現在利用できません。',
  error: 'exportの準備に失敗しました。',
  success: 'exportの依頼を受け付けました。',
};

const SAFE_METADATA_KEYS = ['id', 'label', 'title', 'name', 'locator', 'status', 'reason'];

function asText(value) {
  return typeof value === 'string' ? value.trim() : '';
}

function safeScalar(value) {
  if (typeof value === 'string') return value.trim();
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return '';
}

function safeMetadataItem(value) {
  const scalar = safeScalar(value);
  if (scalar) return scalar;
  if (!value || typeof value !== 'object' || Array.isArray(value)) return '';
  const pieces = SAFE_METADATA_KEYS
    .map((key) => safeScalar(value[key]))
    .filter(Boolean);
  return [...new Set(pieces)].join(' · ');
}

function safeMetadataList(value) {
  if (!Array.isArray(value)) return [];
  return [...new Set(value.map(safeMetadataItem).filter(Boolean))];
}

function objectValue(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

function combineMetadata(...values) {
  return [...new Set(values.flatMap(safeMetadataList))];
}

function sectionCollection(report) {
  if (!report || typeof report !== 'object' || Array.isArray(report)) return null;
  const fields = objectValue(report.fields);
  const sections = report.sections ?? report.chapters ?? fields.sections ?? fields.chapters;
  if (Array.isArray(sections)) {
    return sections.reduce((collection, section, index) => {
      const id = Number(section?.id ?? index);
      if (REPORT_CHAPTER_IDS.has(id)) collection[id] = section;
      return collection;
    }, {});
  }
  if (sections && typeof sections === 'object') {
    return Object.entries(sections).reduce((collection, [key, section]) => {
      const id = Number(section?.id ?? key);
      if (REPORT_CHAPTER_IDS.has(id)) collection[id] = section;
      return collection;
    }, {});
  }
  return null;
}

function sectionMetadata(section, fields, keys) {
  return combineMetadata(
    ...keys.flatMap((key) => [section[key], fields[key]]),
  );
}

function normalizeSection(chapter, section) {
  const source = objectValue(section);
  const metadata = objectValue(source.metadata);
  const fields = objectValue(source.fields);
  const references = sectionMetadata(
    source,
    metadata,
    ['references', 'reference_ids', 'referenceIds', 'citations', 'evidence_ids', 'evidenceIds'],
  ).concat(sectionMetadata(fields, {}, ['references', 'reference_ids', 'citations', 'evidence_ids']));
  const withdrawnClaims = sectionMetadata(
    source,
    metadata,
    ['withdrawn_claims', 'withdrawnClaims'],
  ).concat(sectionMetadata(fields, {}, ['withdrawn_claims', 'withdrawnClaims']));
  return {
    id: chapter.id,
    title: chapter.title,
    present: Boolean(section),
    content: asText(source.content) || asText(source.summary),
    facts: safeMetadataList(source.facts),
    aiInferences: safeMetadataList(source.ai_inferences ?? source.aiInferences),
    unconfirmed: safeMetadataList(source.unconfirmed),
    ownerDecisions: safeMetadataList(source.owner_decisions ?? source.ownerDecisions),
    claimIds: safeMetadataList(source.claim_ids ?? source.claimIds),
    evidenceIds: safeMetadataList(source.evidence_ids ?? source.evidenceIds),
    references: [...new Set(references)],
    withdrawnClaims: [...new Set(withdrawnClaims)],
  };
}

function emptySection(chapter) {
  return normalizeSection(chapter, null);
}

function normalizeReportSections(report) {
  const collection = sectionCollection(report);
  return FOUNDER_GRAPH_REPORT_CHAPTERS.map((chapter) => normalizeSection(chapter, collection?.[chapter.id]));
}

function readReportField(report, fields, ...keys) {
  for (const key of keys) {
    if (report && report[key] !== undefined) return report[key];
    if (fields[key] !== undefined) return fields[key];
  }
  return undefined;
}

/**
 * Keep report diff input at a safe display projection boundary. Only explicit
 * chapter content and provenance metadata are copied into the UI model.
 */
export function projectFounderGraphReportVersion(report) {
  if (!report || typeof report !== 'object' || Array.isArray(report)) return null;
  const fields = objectValue(report.fields);
  if (!sectionCollection(report)) return null;
  const metadata = objectValue(readReportField(report, fields, 'metadata'));
  const references = combineMetadata(
    readReportField(report, fields, 'references'),
    readReportField(report, fields, 'reference_ids', 'referenceIds'),
    readReportField(report, fields, 'citations'),
    readReportField(report, fields, 'evidence_ids', 'evidenceIds'),
    metadata.references,
    metadata.reference_ids,
    metadata.citations,
    metadata.evidence_ids,
  );
  const withdrawnClaims = combineMetadata(
    readReportField(report, fields, 'withdrawn_claims', 'withdrawnClaims'),
    metadata.withdrawn_claims,
    metadata.withdrawnClaims,
  );
  return {
    id: asText(readReportField(report, fields, 'id')) || 'unknown-report',
    status: asText(readReportField(report, fields, 'status')) || 'unknown',
    createdAt: asText(readReportField(report, fields, 'created_at', 'createdAt')),
    parentId: asText(readReportField(report, fields, 'parent_id', 'parentId')),
    supersedesId: asText(readReportField(report, fields, 'supersedes_id', 'supersedesId')),
    changeReason: asText(readReportField(report, fields, 'change_reason', 'changeReason')),
    references,
    withdrawnClaims,
    sections: normalizeReportSections(report),
  };
}

function sectionComparableValue(section) {
  return JSON.stringify({
    present: section.present,
    content: section.content,
    facts: section.facts,
    aiInferences: section.aiInferences,
    unconfirmed: section.unconfirmed,
    ownerDecisions: section.ownerDecisions,
    claimIds: section.claimIds,
    evidenceIds: section.evidenceIds,
    references: section.references,
    withdrawnClaims: section.withdrawnClaims,
  });
}

function changeStatus(previousSection, currentSection) {
  if (!previousSection.present && currentSection.present) return 'added';
  if (previousSection.present && !currentSection.present) return 'removed';
  return sectionComparableValue(previousSection) === sectionComparableValue(currentSection)
    ? 'unchanged'
    : 'changed';
}

export function diffFounderGraphReports(previousReport, currentReport) {
  const previous = projectFounderGraphReportVersion(previousReport);
  const current = projectFounderGraphReportVersion(currentReport);
  const previousSections = previous?.sections ?? FOUNDER_GRAPH_REPORT_CHAPTERS.map(emptySection);
  const currentSections = current?.sections ?? FOUNDER_GRAPH_REPORT_CHAPTERS.map(emptySection);
  return FOUNDER_GRAPH_REPORT_CHAPTERS.map((chapter, index) => ({
    ...chapter,
    status: changeStatus(previousSections[index], currentSections[index]),
    previous: previousSections[index],
    current: currentSections[index],
  }));
}

function normalizeState(value) {
  return ['loading', 'unavailable', 'error', 'empty'].includes(value) ? value : 'ready';
}

function normalizeExportState(value) {
  return ['loading', 'unavailable', 'error', 'success'].includes(value) ? value : 'idle';
}

/**
 * Create a read-only export intent from safe ReportVersion projections.
 * The callback receives identifiers and policy, never the report payload.
 */
export function projectFounderGraphExportIntent(format, reports) {
  if (!FOUNDER_GRAPH_EXPORT_FORMATS.includes(format)) return null;
  const reportIds = [...new Set((Array.isArray(reports) ? reports : [reports])
    .map(projectFounderGraphReportVersion)
    .filter(Boolean)
    .map((report) => report.id))].sort();
  if (reportIds.length === 0) return null;
  return Object.freeze({
    format,
    scope: FOUNDER_GRAPH_EXPORT_SCOPE,
    projection: FOUNDER_GRAPH_EXPORT_PROJECTION,
    reportIds: Object.freeze(reportIds),
  });
}

function focusTab(tabRefs, index) {
  if (typeof requestAnimationFrame !== 'function') {
    tabRefs.current[index]?.focus();
    return;
  }
  requestAnimationFrame(() => tabRefs.current[index]?.focus());
}

function DisplayList({ label, items, testId }) {
  return (
    <div data-founder-graph-report-metadata-group={testId}>
      <dt className="font-semibold text-[var(--color-text-muted)]">{label}</dt>
      <dd className="mt-1">
        {items.length > 0 ? (
          <ul aria-label={label} className="grid gap-1">
            {items.map((item, index) => <li key={`${item}-${index}`} className="break-words">{item}</li>)}
          </ul>
        ) : 'なし'}
      </dd>
    </div>
  );
}

function VersionMeta({ label, report }) {
  if (!report) {
    return (
      <Card className="p-4" data-founder-graph-report-version={label}>
        <h3 className="font-semibold">{label}</h3>
        <p className="mt-2 text-sm text-[var(--color-text-muted)]">この版はありません。</p>
      </Card>
    );
  }
  return (
    <Card className="p-4" data-founder-graph-report-version={label}>
      <div className="flex items-start justify-between gap-3">
        <h3 className="font-semibold">{label}</h3>
        <Badge variant="outline">{report.status}</Badge>
      </div>
      <dl className="mt-3 grid gap-2 text-sm">
        <div><dt className="font-semibold text-[var(--color-text-muted)]">ID</dt><dd className="mt-1 break-words">{report.id}</dd></div>
        {report.createdAt && <div><dt className="font-semibold text-[var(--color-text-muted)]">作成日時</dt><dd className="mt-1 break-words">{report.createdAt}</dd></div>}
        {report.changeReason && <div><dt className="font-semibold text-[var(--color-text-muted)]">変更理由</dt><dd className="mt-1 break-words">{report.changeReason}</dd></div>}
      </dl>
    </Card>
  );
}

function SectionBody({ section }) {
  if (!section.present) {
    return <p className="text-sm text-[var(--color-text-muted)]">この版にはこの章がありません。</p>;
  }
  const groups = [
    ['本文', section.content ? [section.content] : []],
    ['事実', section.facts],
    ['AI推論', section.aiInferences],
    ['未確認', section.unconfirmed],
    ['本人判断', section.ownerDecisions],
  ];
  return (
    <div className="grid gap-4 text-sm">
      {groups.map(([label, items]) => (
        <div key={label}>
          <h4 className="font-semibold text-[var(--color-text-muted)]">{label}</h4>
          {items.length > 0 ? (
            <ul className="mt-1 grid gap-1 leading-6">
              {items.map((item, index) => <li key={`${label}-${index}`} className="break-words">{item}</li>)}
            </ul>
          ) : <p className="mt-1 text-[var(--color-text-muted)]">なし</p>}
        </div>
      ))}
      <dl className="grid gap-3 border-t border-[var(--color-border-subtle)] pt-3">
        <DisplayList label="引用" items={section.references} testId="section-references" />
        <DisplayList label="撤回された主張" items={section.withdrawnClaims} testId="section-withdrawn-claims" />
        <DisplayList label="Claim" items={section.claimIds} testId="section-claim-ids" />
        <DisplayList label="Evidence" items={section.evidenceIds} testId="section-evidence-ids" />
      </dl>
    </div>
  );
}

function ReportVersionMetadata({ label, report }) {
  return (
    <Card className="p-4" data-founder-graph-report-metadata-version={label}>
      <h3 className="font-semibold">{label}</h3>
      <p className="mt-1 text-xs text-[var(--color-text-muted)]">表示のみ。元のReportVersionや主張は変更しません。</p>
      <dl className="mt-3 grid gap-3 text-sm">
        <DisplayList label="引用" items={report?.references ?? []} testId="report-references" />
        <DisplayList label="撤回された主張" items={report?.withdrawnClaims ?? []} testId="report-withdrawn-claims" />
      </dl>
    </Card>
  );
}

export function FounderGraphReportDiff({ previousReport, currentReport, before, after, state, status, initialSection = 0, exportState, exportStatus, onExportRequest }) {
  const headingId = useId();
  const tabRefs = useRef([]);
  const initialIndex = Number.isInteger(initialSection) && initialSection >= 0 && initialSection < FOUNDER_GRAPH_REPORT_CHAPTERS.length
    ? initialSection
    : 0;
  const [activeIndex, setActiveIndex] = useState(initialIndex);
  const resolvedPrevious = previousReport ?? before;
  const resolvedCurrent = currentReport ?? after;
  const previous = useMemo(() => projectFounderGraphReportVersion(resolvedPrevious), [resolvedPrevious]);
  const current = useMemo(() => projectFounderGraphReportVersion(resolvedCurrent), [resolvedCurrent]);
  const resolvedState = normalizeState(state ?? status);
  const resolvedExportState = normalizeExportState(exportState ?? exportStatus);
  const chapters = useMemo(() => diffFounderGraphReports(resolvedPrevious, resolvedCurrent), [resolvedPrevious, resolvedCurrent]);
  const hasReports = Boolean(previous || current);
  const activeChapter = chapters[activeIndex];
  const stateMessage = TRANSIENT_STATE_MESSAGES[resolvedState];
  const exportStateMessage = EXPORT_STATE_MESSAGES[resolvedExportState];
  const showEmpty = resolvedState === 'empty' || (resolvedState === 'ready' && !hasReports);

  function selectChapter(index) {
    setActiveIndex(index);
    focusTab(tabRefs, index);
  }

  function handleTabKeyDown(event, index) {
    let nextIndex = index;
    if (event.key === 'ArrowRight') nextIndex = (index + 1) % FOUNDER_GRAPH_REPORT_CHAPTERS.length;
    else if (event.key === 'ArrowLeft') nextIndex = (index - 1 + FOUNDER_GRAPH_REPORT_CHAPTERS.length) % FOUNDER_GRAPH_REPORT_CHAPTERS.length;
    else if (event.key === 'Home') nextIndex = 0;
    else if (event.key === 'End') nextIndex = FOUNDER_GRAPH_REPORT_CHAPTERS.length - 1;
    else return;
    event.preventDefault();
    selectChapter(nextIndex);
  }

  function requestExport(format) {
    if (resolvedState !== 'ready' || !hasReports || resolvedExportState !== 'idle') return;
    const intent = projectFounderGraphExportIntent(format, [resolvedPrevious, resolvedCurrent]);
    if (intent && typeof onExportRequest === 'function') onExportRequest(intent);
  }

  return (
    <section
      aria-labelledby={`${headingId}-title`}
      aria-busy={resolvedState === 'loading'}
      data-founder-graph-report-diff="true"
      data-founder-graph-report-state={resolvedState}
      data-read-only="true"
      className="mx-auto grid w-full max-w-6xl gap-5"
    >
      <header>
        <p className="text-xs font-semibold uppercase tracking-[.18em] text-[var(--color-text-muted)]">Report diff</p>
        <h1 id={`${headingId}-title`} className="mt-2 text-3xl font-semibold tracking-tight">事業評価レポート差分</h1>
        <p className="mt-2 text-sm text-[var(--color-text-muted)]">8章の変更と、引用・撤回された主張の履歴を表示します。</p>
      </header>

      {stateMessage && (
        <p
          role={resolvedState === 'error' ? 'alert' : 'status'}
          aria-live={resolvedState === 'error' ? 'assertive' : 'polite'}
          data-founder-graph-report-state-message={resolvedState}
          className="rounded-xl border border-[var(--color-border-subtle)] bg-[var(--color-muted)] px-4 py-3 text-sm"
        >
          {stateMessage}
        </p>
      )}

      {showEmpty && (
        <p role="status" aria-live="polite" data-founder-graph-report-state-message="empty" className="rounded-xl border border-[var(--color-border-subtle)] bg-[var(--color-muted)] px-4 py-3 text-sm">
          比較するレポートがありません。2つのReportVersionを指定してください。
        </p>
      )}

      {resolvedState === 'ready' && hasReports && (
        <>
          <div className="grid gap-3 sm:grid-cols-2">
            <VersionMeta label="前版" report={previous} />
            <VersionMeta label="現版" report={current} />
          </div>

          <Card data-founder-graph-report-export="true" data-founder-graph-export-state={resolvedExportState} data-read-only="true" className="p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="font-semibold">safe export</h2>
                <p className="mt-1 text-sm text-[var(--color-text-muted)]">ファイル保存や通信は行わず、safe projectionのexport intentだけを通知します。</p>
              </div>
              <div role="group" aria-label="レポートをexport" className="flex flex-wrap gap-2">
                {FOUNDER_GRAPH_EXPORT_FORMATS.map((format) => (
                  <Button
                    key={format}
                    type="button"
                    variant="secondary"
                    data-founder-graph-export-intent={format}
                    disabled={resolvedExportState !== 'idle'}
                    onClick={() => requestExport(format)}
                  >
                    {format === 'json' ? 'JSONを依頼' : 'Markdownを依頼'}
                  </Button>
                ))}
              </div>
            </div>
            {exportStateMessage && (
              <p
                role={resolvedExportState === 'error' || resolvedExportState === 'unavailable' ? 'alert' : 'status'}
                aria-live={resolvedExportState === 'error' || resolvedExportState === 'unavailable' ? 'assertive' : 'polite'}
                data-founder-graph-export-state-message={resolvedExportState}
                className="mt-3 text-sm text-[var(--color-text-muted)]"
              >
                {exportStateMessage}
              </p>
            )}
          </Card>

          <div data-founder-graph-report-metadata="true" data-read-only="true" className="grid gap-3 sm:grid-cols-2">
            <ReportVersionMetadata label="前版の履歴メタデータ" report={previous} />
            <ReportVersionMetadata label="現版の履歴メタデータ" report={current} />
          </div>

          <div role="tablist" aria-label="事業評価レポートの章" aria-orientation="horizontal" className="flex gap-1 overflow-x-auto border-b border-[var(--color-border-subtle)] pb-px">
            {chapters.map((chapter, index) => {
              const statusDefinition = REPORT_CHANGE_STATUSES[chapter.status];
              return (
                <button
                  key={chapter.id}
                  ref={(node) => { tabRefs.current[index] = node; }}
                  id={`${headingId}-tab-${chapter.id}`}
                  type="button"
                  role="tab"
                  data-founder-graph-report-tab="true"
                  aria-selected={activeIndex === index}
                  aria-controls={`${headingId}-panel`}
                  aria-label={`${chapter.id} ${chapter.title}: ${statusDefinition.label}`}
                  tabIndex={activeIndex === index ? 0 : -1}
                  onClick={() => selectChapter(index)}
                  onKeyDown={(event) => handleTabKeyDown(event, index)}
                  className={`shrink-0 border-b-2 px-3 py-2 text-left text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring)] ${activeIndex === index ? 'border-[var(--color-primary)] text-[var(--color-text)]' : 'border-transparent text-[var(--color-text-muted)] hover:text-[var(--color-text)]'}`}
                >
                  <span className="block">{chapter.id} {chapter.title}</span>
                  <Badge variant={chapter.status === 'changed' || chapter.status === 'added' ? 'default' : 'outline'} data-founder-graph-change-status={chapter.status}>{statusDefinition.label}</Badge>
                </button>
              );
            })}
          </div>

          <div id={`${headingId}-panel`} role="tabpanel" tabIndex="0" aria-labelledby={`${headingId}-tab-${activeChapter.id}`} className="grid gap-5">
            <div className="flex flex-wrap items-center gap-3">
              <h2 className="text-xl font-semibold">{activeChapter.id} {activeChapter.title}</h2>
              <span data-founder-graph-report-panel-status={activeChapter.status} role="status"><Badge variant="outline">{REPORT_CHANGE_STATUSES[activeChapter.status].label}</Badge></span>
              <p className="text-sm text-[var(--color-text-muted)]">{REPORT_CHANGE_STATUSES[activeChapter.status].description}</p>
            </div>
            <div className="grid gap-5 lg:grid-cols-2">
              <Card data-founder-graph-report-column="previous" className="p-5"><h3 className="mb-4 text-sm font-semibold text-[var(--color-text-muted)]">前版</h3><SectionBody section={activeChapter.previous} /></Card>
              <Card data-founder-graph-report-column="current" className="p-5"><h3 className="mb-4 text-sm font-semibold text-[var(--color-text-muted)]">現版</h3><SectionBody section={activeChapter.current} /></Card>
            </div>
          </div>
        </>
      )}
    </section>
  );
}

export default FounderGraphReportDiff;
