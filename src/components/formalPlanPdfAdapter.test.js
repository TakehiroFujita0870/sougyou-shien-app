import { describe, expect, it, vi } from 'vitest';
import { createFormalPlanPdf, downloadFormalPlanPdf } from './formalPlanPdfAdapter';

const project = {
  name: '保全履歴の共有サービス',
  overview: '工場の保全担当者が履歴を探せない課題を解決します。',
  sections: {
    'どんな事業？': { status: '確認中', summary: '履歴を検索できるサービス', evidence: 'ヒアリング記録', unknown: '導入部門数' },
    '市場はある？': { status: '未確定', summary: '市場規模を確認中', evidence: '公開資料', unknown: '一次調査' },
    '競合は誰？': { status: '確認中', summary: '直接・間接・代替を比較', evidence: '比較メモ', unknown: '価格表' },
    '利益はでる？': { status: '試算中', summary: '単位経済性を試算', evidence: '管理会計', unknown: '継続率' },
    '実現できる？': { status: '確認中', summary: '小さく検証する', evidence: '実行計画', unknown: '資金計画' },
  },
  decisions: [{ kind: '採用', title: '現場ヒアリングから始める', reason: '低リスクで検証できるため' }],
};

describe('formal plan PDF adapter', () => {
  it('creates a Japanese PDF that can be inspected outside the browser', async () => {
    const bytes = new Uint8Array(await (await createFormalPlanPdf(project)).arrayBuffer());
    if (process.env.KADODE_PDF_QA_PATH) await (await import('node:fs/promises')).writeFile(process.env.KADODE_PDF_QA_PATH, bytes);
    expect(new TextDecoder().decode(bytes.slice(0, 8))).toMatch(/^%PDF-1\.[4-7]$/);
    expect(bytes.length).toBeGreaterThan(1_000);
  }, 15000);

  it('downloads only the generated PDF through a browser object URL', async () => {
    const click = vi.fn();
    const remove = vi.fn();
    const documentRef = { body: { append: vi.fn() }, createElement: vi.fn(() => ({ click, remove })) };
    const url = { createObjectURL: vi.fn(() => 'blob:formal-plan-pdf'), revokeObjectURL: vi.fn() };
    const blob = await downloadFormalPlanPdf(project, { documentRef, url });
    expect(blob.type).toBe('application/pdf');
    expect(documentRef.body.append).toHaveBeenCalledOnce();
    expect(click).toHaveBeenCalledOnce();
    expect(url.revokeObjectURL).toHaveBeenCalledWith('blob:formal-plan-pdf');
  });
});
