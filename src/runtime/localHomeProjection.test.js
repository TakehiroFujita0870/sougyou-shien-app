import { describe, expect, it } from 'vitest';
import { projectLocalHome } from './localHomeProjection.js';
import { LocalDashboardClientError } from './localDashboardClient.js';

describe('local home projection independent of transport', () => {
  it('keeps the existing error identity and rejects malformed payloads', () => {
    expect(() => projectLocalHome({ status: 'ready', ideas: [], assets: [{}] })).toThrow(LocalDashboardClientError);
  });
  it('projects only home fields without retaining caller-owned arrays', () => {
    const payload = {
      status: 'ready', ideas: [], assets: [{ id: 'asset', name: 'Capability', description: 'Synthetic', revision: 1, egress_policy: 'local_only', category: 'criterion', secret: 'not projected' }],
      profile: { display_name: 'Synthetic owner', private: 'not projected' }, secret: 'not projected',
    };
    expect(projectLocalHome(payload)).toEqual({ status: 'ready', ideas: [], assets: [{ id: 'asset', name: 'Capability', description: 'Synthetic', revision: 1, egress_policy: 'local_only', kind: 'asset', category: 'criterion' }], profile: { displayName: 'Synthetic owner' } });
    expect(projectLocalHome(payload).assets).not.toBe(payload.assets);
  });
  it('keeps the barrier distinction while treating older assets as strengths', () => {
    const asset = { id: 'a', name: 'ためらい', description: '価格が不安', revision: 1, egress_policy: 'local_only' };
    const result = projectLocalHome({ status: 'ready', ideas: [], assets: [{ ...asset, kind: 'barrier' }, { ...asset, id: 'b' }], profile: null });
    expect(result.assets.map((item) => item.kind)).toEqual(['barrier', 'asset']);
    expect(result.assets.map((item) => item.category)).toEqual(['barrier', 'strength']);
  });
  it('preserves valid explicit categories and rejects unknown category values', () => {
    const asset = { id: 'a', name: '判断基準', description: 'Synthetic', revision: 1, egress_policy: 'local_only' };
    expect(projectLocalHome({ status: 'ready', ideas: [], assets: [{ ...asset, category: 'criterion' }], profile: null }).assets[0].category).toBe('criterion');
    expect(() => projectLocalHome({ status: 'ready', ideas: [], assets: [{ ...asset, category: 'person' }], profile: null })).toThrow(LocalDashboardClientError);
  });
});
