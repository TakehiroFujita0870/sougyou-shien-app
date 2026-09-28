import { safePublicCitationUrl } from './publicCitationUrl.js';
import { LocalDashboardClientError } from './localDashboardClientError.js';

/** Allowlisted home presentation data, independent of the HTTP transport. */
export function projectLocalHome(result) {
  if (!['ready', 'empty', 'stopped'].includes(result.status) || !Array.isArray(result.ideas) || !Array.isArray(result.assets)) {
    throw new LocalDashboardClientError('error');
  }
  const ideas = result.ideas.map((item) => {
    if (!item || typeof item.id !== 'string' || typeof item.title !== 'string' || typeof item.summary !== 'string' || typeof item.description !== 'string') throw new LocalDashboardClientError('error');
    const idea = { id: item.id, title: item.title, summary: item.summary, description: item.description };
    if (item.revision !== undefined) {
      if (!Number.isSafeInteger(item.revision) || item.revision < 0) throw new LocalDashboardClientError('error');
      idea.revision = item.revision;
    }
    idea.research_status = item.research_status === 'unresearched' ? 'unresearched' : 'unknown';
    if (item.brief_sections !== undefined || item.brief_revision !== undefined) {
      if (!Array.isArray(item.brief_sections) || item.brief_sections.length !== 8
        || item.brief_sections.some((section) => typeof section !== 'string')
        || !Number.isSafeInteger(item.brief_revision) || item.brief_revision < 1) {
        throw new LocalDashboardClientError('error');
      }
      idea.brief_sections = [...item.brief_sections];
      idea.brief_revision = item.brief_revision;
      if (item.report_markdown !== undefined) {
        if (typeof item.report_markdown !== 'string' || !item.report_markdown.trim() || item.report_markdown.length > 60_000) throw new LocalDashboardClientError('error');
        idea.report_markdown = item.report_markdown;
      }
      if (item.brief_citations !== undefined) {
        if (!Array.isArray(item.brief_citations) || item.brief_citations.length !== 8
          || item.brief_citations.some((chapter) => !Array.isArray(chapter) || chapter.length > 100)) {
          throw new LocalDashboardClientError('error');
        }
        idea.brief_citations = item.brief_citations.map((chapter) => chapter.flatMap((citation) => {
          if (!citation || typeof citation.url !== 'string' || citation.url.length > 2048
            || typeof citation.title !== 'string' || !citation.title.trim() || citation.title.length > 500) return [];
          const url = safePublicCitationUrl(citation.url);
          return url ? [{ url, title: citation.title.trim() }] : [];
        }));
      }
      if (item.brief_origin === 'prior_research_import') {
        idea.brief_origin = 'prior_research_import';
        const hasCurrentCitations = idea.brief_citations?.some((chapter) => chapter.length > 0) ?? false;
        idea.research_status = hasCurrentCitations ? 'prior_research_import' : 'prior_research_sources_missing';
      }
      if (!idea.brief_origin && item.research_status === 'research_sources_missing' && idea.brief_sections.every((section) => section.trim())) {
        idea.research_status = 'research_sources_missing';
      }
      if (!idea.brief_origin && item.research_status === 'researched' && idea.brief_sections.every((section) => section.trim())) {
        idea.research_status = 'researched';
      }
    }
    return idea;
  });
  const assets = result.assets.map((item) => {
    if (!item || typeof item.id !== 'string' || !item.id || typeof item.name !== 'string' || typeof item.description !== 'string'
      || !Number.isSafeInteger(item.revision) || item.revision < 1 || !['local_only', 'shareable'].includes(item.egress_policy)) {
      throw new LocalDashboardClientError('error');
    }
    return { id: item.id, name: item.name, description: item.description, revision: item.revision, egress_policy: item.egress_policy, kind: item.kind === 'barrier' ? 'barrier' : 'asset' };
  });
  const profile = result.profile && typeof result.profile.display_name === 'string' ? { displayName: result.profile.display_name } : null;
  return { status: result.status, ideas, assets, profile };
}
