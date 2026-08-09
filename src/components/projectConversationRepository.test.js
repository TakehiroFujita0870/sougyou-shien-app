import { describe, expect, it } from 'vitest';
import { PROJECT_CONVERSATION_QUARANTINE_KEY, PROJECT_CONVERSATION_STORAGE_KEY, createProjectConversationRepository } from './projectConversationRepository';

function memoryStorage(initial = {}) {
  const values = new Map(Object.entries(initial));
  return { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value), values };
}

describe('project conversation repository', () => {
  it('restores only matching owner, space, and project records', async () => {
    const storage = memoryStorage();
    const first = createProjectConversationRepository({ ownerId: 'owner-a', spaceId: 'space-a', projectId: 'project-a', storage });
    await first.save([{ role: 'user', content: 'A' }]);
    const otherProject = createProjectConversationRepository({ ownerId: 'owner-a', spaceId: 'space-a', projectId: 'project-b', storage });
    const otherOwner = createProjectConversationRepository({ ownerId: 'owner-b', spaceId: 'space-a', projectId: 'project-a', storage });
    expect(await createProjectConversationRepository({ ownerId: 'owner-a', spaceId: 'space-a', projectId: 'project-a', storage }).load()).toHaveLength(1);
    expect(await otherProject.load()).toEqual([]);
    expect(await otherOwner.load()).toEqual([]);
  });

  it('quarantines corrupt storage and refuses a replacement write', async () => {
    const storage = memoryStorage({ [PROJECT_CONVERSATION_STORAGE_KEY]: '{broken' });
    const repository = createProjectConversationRepository({ storage });
    expect(await repository.load()).toEqual([]);
    expect(storage.getItem(PROJECT_CONVERSATION_QUARANTINE_KEY)).toBe('{broken');
    await expect(repository.save([{ role: 'user', content: 'do not overwrite' }])).rejects.toThrow('recovery');
    expect(storage.getItem(PROJECT_CONVERSATION_STORAGE_KEY)).toBe('{broken');
  });
});
