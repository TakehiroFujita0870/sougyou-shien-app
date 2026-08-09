import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { FileLibrary, createFakeDocumentRepository, validateUpload } from './FileLibrary';

describe('file ingestion UI model', () => {
  it('rejects unsupported formats and files beyond the provisional limit', () => {
    expect(validateUpload({ name: 'run.exe', size: 12 }).reason).toContain('PDF');
    expect(validateUpload({ name: 'large.pdf', size: 25 * 1024 * 1024 + 1 }).reason).toContain('25 MiB');
  });

  it('creates, retries, versions, and deletes through the fake repository', async () => {
    const repository = createFakeDocumentRepository([{ id: 'failed', name: 'notes.txt', version: 1, state: 'failed' }]);
    expect((await repository.retry('failed')).state).toBe('processing');
    expect((await repository.addVersion('failed', { name: 'notes-v2.txt', size: 20 })).version).toBe(2);
    expect((await repository.remove('failed')).state).toBe('deleted');
  });

  it('renders status, upload guidance, and a deletion control', () => {
    const html = renderToStaticMarkup(<FileLibrary repository={createFakeDocumentRepository()} initialDocuments={[{ id: 'a', name: 'brief.pdf', version: 1, state: 'failed' }]} />);
    expect(html).toContain('資料を追加');
    expect(html).toContain('解析に失敗');
    expect(html).toContain('削除');
  });

  it('shows only available references with source and locator, without an owner control', () => {
    const html = renderToStaticMarkup(<FileLibrary initialDocuments={[{ id: 'a', name: 'brief.pdf', version: 1, state: 'searchable', references: [{ kind: 'project', sourceId: 'project-1', locator: 'p. 2' }, { kind: 'research', sourceId: 'research-2', locator: 'p. 4', status: 'unavailable' }] }, { id: 'deleted', name: 'removed.pdf', version: 1, state: 'deleted', references: [{ kind: 'idea', sourceId: 'idea-1', locator: 'p. 1' }] }]} />);
    expect(html).toContain('project: project-1 · p. 2');
    expect(html).not.toContain('research-2');
    expect(html).not.toContain('removed.pdf');
    expect(html).not.toMatch(/owner|principal|grant/i);
  });

  it('keeps hydrated space references visible after a fresh render without reviving deleted records', () => {
    const hydrated = [{ id: 'saved', name: 'shared.txt', version: 1, state: 'searchable', references: [{ kind: 'conversation', sourceId: 'conversation-1', locator: '段落 1' }] }, { id: 'deleted', name: 'gone.txt', version: 1, state: 'deleted' }];
    const afterReload = renderToStaticMarkup(<FileLibrary initialDocuments={hydrated} />);
    expect(afterReload).toContain('conversation: conversation-1 · 段落 1');
    expect(afterReload).not.toContain('gone.txt');
  });
});
