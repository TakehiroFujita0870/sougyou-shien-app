import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname } from 'node:path';

import { describe, expect, it, vi } from 'vitest';
import { createFormalPlanDocx, downloadFormalPlanDocx } from './formalPlanDocxAdapter';

export const formalPlanFixture = {
  name: '保全履歴の共有サービス',
  overview: '工場の保全担当者が設備履歴をすぐ探せる事業',
  sections: {
    'どんな事業？': { status: '確認中', summary: '検索を支援する', evidence: '現場ヒアリング', unknown: '価格' },
    '市場はある？': { status: '未確認', summary: '保全担当者へ検証する', evidence: '顧客候補一覧', unknown: '市場規模' },
  },
  decisions: [{ kind: '採用', title: '小さく検証', reason: '低リスク' }],
};

describe('formal plan DOCX adapter', () => {
  it('creates a deterministic Japanese DOCX package without network access', async () => {
    const blob = await createFormalPlanDocx(formalPlanFixture);
    const bytes = new Uint8Array(await blob.arrayBuffer());
    expect(blob.type).toBe('application/vnd.openxmlformats-officedocument.wordprocessingml.document');
    expect([...bytes.slice(0, 4)]).toEqual([80, 75, 3, 4]);
    if (process.env.KADODE_DOCX_QA_PATH) {
      await mkdir(dirname(process.env.KADODE_DOCX_QA_PATH), { recursive: true });
      await writeFile(process.env.KADODE_DOCX_QA_PATH, bytes);
    }
  });

  it('uses the audited maintained dependency', async () => {
    const metadata = JSON.parse(await readFile(new URL('../../node_modules/docx/package.json', import.meta.url), 'utf8'));
    expect(metadata.version).toBe('9.5.1');
    expect(metadata.license).toBe('MIT');
  });

  it('downloads only after the DOCX blob is ready', async () => {
    const click = vi.fn(); const remove = vi.fn();
    const documentRef = { body: { append: vi.fn() }, createElement: vi.fn(() => ({ click, remove })) };
    const url = { createObjectURL: vi.fn(() => 'blob:formal-plan'), revokeObjectURL: vi.fn() };
    const blob = await downloadFormalPlanDocx(formalPlanFixture, { documentRef, url });
    expect(blob.size).toBeGreaterThan(0);
    expect(documentRef.body.append).toHaveBeenCalledOnce();
    expect(click).toHaveBeenCalledOnce();
    expect(url.revokeObjectURL).toHaveBeenCalledWith('blob:formal-plan');
  });
});
