import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { AiPublicRelationsDraftWorkflow, statusLabel } from './AiPublicRelationsDraftWorkflow';

describe('AiPublicRelationsDraftWorkflow', () => {
  it('shows the local-only safety notice without a posting action', () => {
    const html = renderToStaticMarkup(<AiPublicRelationsDraftWorkflow />);

    expect(html).toContain('外部公開やXへの投稿は行いません。');
    expect(html).toContain('下書きを保存');
    expect(html).toContain('CEOの判断を保存');
    expect(html).not.toContain('Xに投稿');
  });

  it('uses understandable labels for all approval states', () => {
    expect(statusLabel('draft')).toBe('下書き');
    expect(statusLabel('revision_requested')).toBe('修正依頼');
    expect(statusLabel('approved')).toBe('承認');
    expect(statusLabel('rejected')).toBe('却下');
  });
});
