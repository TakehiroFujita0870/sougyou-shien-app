export const DEMO_PRINCIPAL = Object.freeze({ id: 'demo-admin-principal', kind: 'demo', displayName: 'Kadode Demo Admin' });
export const DEMO_OWNER_ID = 'demo-owner';
export const DEMO_SPACE_ID = 'demo-space';
const SEED = Object.freeze({ documents: [{ id: 'demo-doc-1', ownerId: DEMO_OWNER_ID, spaceId: DEMO_SPACE_ID, name: 'Demo brief', state: 'searchable' }], ideas: [{ id: 'demo-idea-1', ownerId: DEMO_OWNER_ID, spaceId: DEMO_SPACE_ID, title: 'Demo idea' }] });

function cloneSeed() { return JSON.parse(JSON.stringify(SEED)); }

export function createDemoSessionAdapter() {
  let active = false;
  let fixture = cloneSeed();
  return {
    principal: DEMO_PRINCIPAL,
    ownerId: DEMO_OWNER_ID,
    spaceId: DEMO_SPACE_ID,
    start() { active = true; return DEMO_PRINCIPAL; },
    end() { active = false; },
    isActive() { return active; },
    getFixture() { if (!active) throw new Error('Demo session is not active.'); return cloneSeedWithBoundary(fixture); },
    reset() { fixture = cloneSeed(); },
  };
}

function cloneSeedWithBoundary(value) {
  return { documents: value.documents.filter((item) => item.ownerId === DEMO_OWNER_ID && item.spaceId === DEMO_SPACE_ID).map((item) => ({ ...item })), ideas: value.ideas.filter((item) => item.ownerId === DEMO_OWNER_ID && item.spaceId === DEMO_SPACE_ID).map((item) => ({ ...item })) };
}
