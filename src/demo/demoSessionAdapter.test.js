import { describe, expect, it } from 'vitest';
import { createDemoSessionAdapter, DEMO_OWNER_ID, DEMO_PRINCIPAL, DEMO_SPACE_ID } from './demoSessionAdapter';

describe('demo session adapter', () => {
  it('requires an explicit demo session and exposes bounded fixtures', () => {
    const adapter = createDemoSessionAdapter();
    expect(adapter.isActive()).toBe(false);
    expect(() => adapter.getFixture()).toThrow();
    expect(adapter.start()).toEqual(DEMO_PRINCIPAL);
    const fixture = adapter.getFixture();
    expect(fixture.documents[0]).toMatchObject({ ownerId: DEMO_OWNER_ID, spaceId: DEMO_SPACE_ID });
    expect(JSON.stringify(fixture)).not.toMatch(/email|token|secret|password/i);
  });

  it('returns isolated fixture clones and reset restores the seed', () => {
    const adapter = createDemoSessionAdapter();
    adapter.start();
    const first = adapter.getFixture();
    first.documents.push({ id: 'leak', ownerId: 'production-user', spaceId: 'prod' });
    adapter.reset();
    const second = adapter.getFixture();
    expect(second.documents.map(({ id }) => id)).toEqual(['demo-doc-1']);
    adapter.end();
    expect(adapter.isActive()).toBe(false);
  });
});
