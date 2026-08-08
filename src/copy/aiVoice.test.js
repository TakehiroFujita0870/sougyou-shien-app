import { describe, expect, it } from 'vitest';

import { AI_COPY_CATALOG, AI_OUTPUT_CONTRACT, AI_TONES, formatAiOutput } from './aiVoice';

describe('AI voice catalog', () => {
  it('defines the supportive and candid voice used by the first idea experience', () => {
    expect(Object.keys(AI_COPY_CATALOG)).toHaveLength(8);
    expect(Object.keys(AI_TONES)).toHaveLength(4);
    expect(AI_TONES.empowering).toContain('強み');
    expect(AI_TONES.candid).toContain('反対意見');
    expect(AI_COPY_CATALOG.welcome.body).toContain('無理のない次の一歩');
    expect(AI_COPY_CATALOG.inference.body).toContain('賛成材料と反対意見');
  });

  it('keeps legal, financial, and success claims non-conclusive', () => {
    const allCopy = Object.values(AI_COPY_CATALOG)
      .flatMap((entry) => [entry.heading, entry.body])
      .join('');

    expect(allCopy).not.toMatch(/法的に問題ない|融資を受けられる|成功します/);
  });
});

describe('AI output contract', () => {
  it('separates facts, AI inference, uncertainty, and the user decision', () => {
    expect(AI_OUTPUT_CONTRACT).toEqual(['facts', 'inference', 'uncertainty', 'userDecision']);
    expect(formatAiOutput({
      facts: ['一次情報を確認'],
      inference: '検証候補です',
      uncertainty: ['対象顧客は未確認'],
      userDecision: '保留する',
    })).toEqual({
      facts: ['一次情報を確認'],
      inference: '検証候補です',
      uncertainty: ['対象顧客は未確認'],
      userDecision: '保留する',
    });
  });
});
