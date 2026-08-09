import { describe, expect, it, vi } from 'vitest';
import { createFormalPlanDocx, downloadFormalPlanDocx } from './formalPlanDocxAdapter';

const project = { name: '設備保全ノート', overview: '保全記録を探しやすくする事業', sections: { 'どんな事業': { status: '確認中', summary: '検索を支援', evidence: '顧客ヒアリング', unknown: '価格' } }, decisions: [{ kind: '採用', title: '小さく検証', reason: '低リスク' }] };

describe('formal plan DOCX adapter', () => {
  it('creates an editable DOCX package without network access', async () => {
    const blob = createFormalPlanDocx(project); const bytes = new Uint8Array(await blob.arrayBuffer());
    expect(blob.type).toBe('application/vnd.openxmlformats-officedocument.wordprocessingml.document'); expect([...bytes.slice(0, 4)]).toEqual([80, 75, 3, 4]); expect(new TextDecoder().decode(bytes)).toContain('word/document.xml');
  });
  it('downloads only a DOCX after the browser object URL is created', () => {
    const click = vi.fn(); const remove = vi.fn(); const documentRef = { body: { append: vi.fn() }, createElement: vi.fn(() => ({ click, remove })) }; const url = { createObjectURL: vi.fn(() => 'blob:formal-plan'), revokeObjectURL: vi.fn() };
    downloadFormalPlanDocx(project, { documentRef, url }); expect(documentRef.body.append).toHaveBeenCalledOnce(); expect(click).toHaveBeenCalledOnce(); expect(url.revokeObjectURL).toHaveBeenCalledWith('blob:formal-plan');
  });
});
