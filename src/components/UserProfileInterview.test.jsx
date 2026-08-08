import { describe, expect, it } from 'vitest';
import { EMPTY_PROFILE, PROFILE_STEPS, advanceProfile, persistProfile, validateProfileStep } from './UserProfileInterview';
const answers = Object.fromEntries(PROFILE_STEPS.map(([key]) => [key, '回答']));
describe('profile conversation model', () => {
  it('starts with validation', () => expect(validateProfileStep(EMPTY_PROFILE, 0)).toContain('入力'));
  it('resumes an interrupted answer', () => expect(advanceProfile({ values: answers, step: 2, status: 'in_progress' }).step).toBe(3));
  it('completes and supports editing values', () => expect(advanceProfile({ values: answers, step: 5, status: 'in_progress' }).status).toBe('completed'));
  it('exposes save failures at the repository boundary', async () => expect((await persistProfile({ save: async () => { throw new Error('offline'); } }, answers)).error).toContain('保存'));
});
