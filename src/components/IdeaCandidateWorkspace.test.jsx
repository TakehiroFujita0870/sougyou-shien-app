import { describe, expect, it } from 'vitest';
import { approveCandidate, findDuplicate, saveCandidate } from './IdeaCandidateWorkspace';
const candidate = { title: '工場ノート', summary: '設備保全を記録', pain: '履歴が探せない' };
describe('idea candidate repository boundary', () => {
  it('saves a candidate and detects duplicates', async () => { const repository = { save: async (items) => items }; const result = await saveCandidate(repository, [], candidate); expect(result.items).toHaveLength(1); expect(findDuplicate(result.items, candidate)).toBeTruthy(); });
  it('updates only after approval', async () => { const repository = { save: async (items) => items }; const result = await approveCandidate(repository, [{ ...candidate, id: '1' }], { ...candidate, id: '1', title: '更新案' }); expect(result.items[0].title).toBe('更新案'); });
  it('returns a recoverable save failure', async () => { const result = await saveCandidate({ save: async () => { throw new Error('offline'); } }, [], candidate); expect(result.error).toContain('保存'); });
});
