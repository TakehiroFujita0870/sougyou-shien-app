import { describe, expect, it } from 'vitest';

import { createAiPublicRelationsDraftRepository, validateDraftContent } from './AiPublicRelationsDraftRepository';

describe('validateDraftContent', () => {
  it('rejects personal information and secrets before a draft is saved', () => {
    expect(validateDraftContent('連絡先は owner@example.com です。')).toEqual({
      content: '個人情報または秘密情報が含まれている可能性があります。削除または置換してください。',
    });
    expect(validateDraftContent('API_KEY=super-secret-value')).toEqual({
      content: '個人情報または秘密情報が含まれている可能性があります。削除または置換してください。',
    });
  });

  it('accepts a safe draft within the X draft character limit', () => {
    expect(validateDraftContent('新しい設備保全ノートの検証を始めました。')).toEqual({});
  });
});

describe('createAiPublicRelationsDraftRepository', () => {
  it('saves draft, revision request, approval and rejection states locally', () => {
    const repository = createAiPublicRelationsDraftRepository();
    const draft = repository.create({ content: '現場の知見を次の検証に活かします。' });

    expect(draft.status).toBe('draft');
    expect(repository.requestRevision(draft.id, '根拠を一文追加してください。').status).toBe('revision_requested');
    expect(repository.approve(draft.id).status).toBe('approved');
    expect(repository.reject(draft.id, '公開方針と合わないため。').status).toBe('rejected');
    expect(repository.list()).toHaveLength(1);
  });

  it('does not save unsafe content', () => {
    const repository = createAiPublicRelationsDraftRepository();

    expect(() => repository.create({ content: '電話番号は090-1234-5678です。' })).toThrow('個人情報または秘密情報');
    expect(repository.list()).toHaveLength(0);
  });
});
