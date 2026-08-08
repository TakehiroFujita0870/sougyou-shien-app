import { describe, expect, it } from 'vitest';

import { validateIdea } from './IdeaForm';

describe('validateIdea', () => {
  it('requires all three idea fields', () => {
    expect(validateIdea({ title: '', ideaSummary: '', painStatement: '' })).toEqual({
      title: 'アイデア名を入力してください。',
      ideaSummary: 'アイデアの概要を入力してください。',
      painStatement: '誰の、何のペインかを入力してください。',
    });
  });

  it('accepts a complete idea draft', () => {
    expect(
      validateIdea({
        title: '設備保全ノート',
        ideaSummary: '復旧手順を構造化する。',
        painStatement: '保全担当者が過去の故障記録を探す時間を失う。',
      }),
    ).toEqual({});
  });
});
