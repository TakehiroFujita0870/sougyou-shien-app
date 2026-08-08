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
});
