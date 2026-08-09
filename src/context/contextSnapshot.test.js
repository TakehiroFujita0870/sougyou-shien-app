import { describe, expect, it } from 'vitest';

import { createLocalContextSnapshot } from './contextSnapshot';

const ownerId = 'owner-a';
const selectedProject = { id: 'project-1', displayName: 'Project One', locator: 'project:project-1', revision: 'r2', ownerId, permission: 'read', rawUploadBody: 'do not include' };

describe('local context snapshot', () => {
  it('creates a deterministic allowlisted Home, Project, or Knowledge snapshot', () => {
    const input = {
      ownerId,
      surface: { name: 'Project', route: '/projects/project-1', view: 'detail', subview: 'overview' },
      selected: { project: selectedProject },
      selection: ['decision-2', 'asset-1'],
      dirtyState: [{ entityId: 'project-1', dirty: true, explicit: true }],
      sources: [
        { kind: 'inference', entityId: 'decision-2', locator: 'decision:decision-2', revision: 'r1', ownerId, permission: 'read' },
        { kind: 'fact', entityId: 'asset-1', locator: 'asset:asset-1', revision: 'r3', ownerId, permission: 'read' },
      ],
    };

    const first = createLocalContextSnapshot(input);
    const second = createLocalContextSnapshot({ ...input, selection: [...input.selection].reverse(), sources: [...input.sources].reverse() });

    expect(first).toEqual(second);
    expect(first).toEqual({
      version: 1,
      surface: { name: 'Project', route: '/projects/project-1', view: 'detail', subview: 'overview' },
      selected: { project: { id: 'project-1', displayName: 'Project One', locator: 'project:project-1', revision: 'r2' } },
      selection: ['asset-1', 'decision-2'],
      dirtyState: [{ entityId: 'project-1', dirty: true }],
      sources: [
        { kind: 'fact', entityId: 'asset-1', locator: 'asset:asset-1', revision: 'r3' },
        { kind: 'inference', entityId: 'decision-2', locator: 'decision:decision-2', revision: 'r1' },
      ],
    });
  });

  it('excludes cross-owner, hidden, deleted, unauthorized, malformed, and sensitive inputs', () => {
    const snapshot = createLocalContextSnapshot({
      ownerId,
      surface: { name: 'Knowledge' },
      selected: {
        project: { ...selectedProject, ownerId: 'owner-b' },
        asset: { id: 'asset-1', displayName: 'Visible asset', locator: 'asset:asset-1', revision: 'r1', ownerId, permission: 'read', profileDetails: 'exclude' },
        decision: { id: 'decision-1', displayName: 'Deleted decision', locator: 'decision:decision-1', revision: 'r1', ownerId, permission: 'read', deleted: true },
      },
      dirtyState: [
        { entityId: 'asset-1', dirty: true, explicit: true, raw: 'raw upload body and auth token secret' },
        { entityId: 'project-1', dirty: true, explicit: true, secret: 'hidden knowledge text' },
        { entityId: 'unknown', dirty: true, explicit: true, token: 'unselected data' },
        { entityId: 'asset-1', dirty: false, explicit: true, value: 'not dirty' },
      ],
      sources: [
        { kind: 'fact', entityId: 'asset-1', locator: '', revision: 'r1', ownerId, permission: 'read' },
        { kind: 'fact', entityId: 'asset-2', locator: 'asset:asset-2', revision: 'r1', ownerId: 'owner-b', permission: 'read' },
        { kind: 'fact', entityId: 'asset-3', locator: 'asset:asset-3', revision: 'r1', ownerId, permission: 'none' },
        { kind: 'fact', entityId: 'asset-4', locator: 'asset:asset-4', revision: 'r1', ownerId, permission: 'read', hidden: true },
        { kind: 'fact', entityId: 'asset-5', locator: 'asset:asset-5', revision: 'r1', ownerId, permission: 'read', deleted: true },
      ],
      authToken: 'exclude',
      secret: 'exclude',
      rawUploadBody: 'exclude',
    });

    expect(snapshot.selected).toEqual({ asset: { id: 'asset-1', displayName: 'Visible asset', locator: 'asset:asset-1', revision: 'r1' } });
    expect(snapshot.dirtyState).toEqual([{ entityId: 'asset-1', dirty: true }]);
    expect(snapshot.sources).toEqual([]);
    expect(JSON.stringify(snapshot)).not.toContain('exclude');
    expect(JSON.stringify(snapshot)).not.toContain('raw upload body');
    expect(JSON.stringify(snapshot)).not.toContain('auth token secret');
    expect(JSON.stringify(snapshot)).not.toContain('hidden knowledge text');
  });

  it('ignores raw dirtyChanges and rejects non-metadata dirty-state values', () => {
    const snapshot = createLocalContextSnapshot({
      ownerId,
      surface: { name: 'Project' },
      selected: { project: selectedProject },
      selection: ['project-1', 'raw upload body and token secret'],
      dirtyChanges: [{ entityId: 'project-1', value: 'raw upload body and token secret', explicit: true }],
      dirtyState: [
        'raw upload body',
        { entityId: 'project-1', dirty: true, explicit: true, token: 'token-value', secret: 'secret-value' },
        { entityId: 'project-1', dirty: false, explicit: true, raw: 'raw-value' },
      ],
      sources: { token: 'not-an-array' },
    });

    expect(snapshot.selection).toEqual(['project-1']);
    expect(snapshot.dirtyState).toEqual([{ entityId: 'project-1', dirty: true }]);
    expect(JSON.stringify(snapshot)).not.toContain('raw upload body');
    expect(JSON.stringify(snapshot)).not.toContain('token-value');
    expect(JSON.stringify(snapshot)).not.toContain('secret-value');
    expect(JSON.stringify(snapshot)).not.toContain('raw-value');
    expect(snapshot).not.toHaveProperty('dirtyChanges');
  });
});
