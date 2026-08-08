import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { ResearchWorkspace, createLocalResearchRepository } from './ResearchWorkspace';

describe('research workspace local contract', () => {
  it('keeps locators for every selected source and separates inference', async () => {
    const result = await createLocalResearchRepository().run('保全', ['web', 'patent', 'document', 'decision']);
    expect(result.evidence.map((item) => item.locator)).toEqual(expect.arrayContaining(['https://example.test/maintenance-market', 'JP2023-123456A', 'document:brief-1#page=3', 'decision:dec-42']));
    expect(result.inference).toContain('仮説');
  });

  it('preserves evidence when another source has a partial failure', async () => {
    const result = await createLocalResearchRepository({ sourceStatus: { patent: 'timeout: retry the source' } }).run('保全', ['web', 'patent']);
    expect(result.status).toBe('partial');
    expect(result.source_status.patent).toContain('timeout');
    expect(result.evidence).toHaveLength(1);
  });

  it('renders source choices and the local-data boundary', () => {
    const html = renderToStaticMarkup(<ResearchWorkspace repository={createLocalResearchRepository()} />);
    expect(html).toContain('JPO');
    expect(html).toContain('外部サービスへ送信しません');
  });
});
