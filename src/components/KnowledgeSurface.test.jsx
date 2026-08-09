import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import fixture from '../fixtures/knowledge-admin-demo.json';
import { KnowledgeSurface } from './KnowledgeSurface';

describe('KnowledgeSurface', () => {
  it('shows asset metadata, available references, project context, and decision fields without PII', () => {
    const html = renderToStaticMarkup(<KnowledgeSurface fixture={fixture} />);
    expect(html).toContain('合成事業メモ');
    expect(html).toContain('source: demo-source-market · fixture:document/1');
    expect(html).toContain('本業と家計の制約を守るため');
    expect(html).toContain('可逆な週末検証から開始する事業仮説');
    expect(html).toContain('synthetic_demo');
    expect(html).not.toMatch(/email|phone|address|個人名|ownerId|spaceId/i);
  });

  it('exposes add, delete confirmation, and composer controls', () => {
    const html = renderToStaticMarkup(<KnowledgeSurface fixture={fixture} />);
    expect(html).toContain('削除を確定');
    expect(html).toContain('KnowledgeについてKadode AIに相談');
    expect(html).toContain('資料について考えていることを入力');
    expect(renderToStaticMarkup(<KnowledgeSurface fixture={null} />)).toContain('資料を追加');
  });
});
