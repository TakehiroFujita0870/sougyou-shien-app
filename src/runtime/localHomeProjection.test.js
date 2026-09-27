import { describe, expect, it } from 'vitest';
import { projectLocalHome } from './localHomeProjection.js';
import { LocalDashboardClientError } from './localDashboardClient.js';

describe('local home projection independent of transport', () => {
  it('keeps the existing error identity and rejects malformed payloads', () => {
    expect(() => projectLocalHome({ status: 'ready', ideas: [], assets: [{}] })).toThrow(LocalDashboardClientError);
  });
  it('projects only home fields without retaining caller-owned arrays', () => {
    const payload = {
      status: 'ready', ideas: [], assets: [{ id: 'asset', name: 'Capability', description: 'Synthetic', revision: 1, egress_policy: 'local_only', secret: 'not projected' }],
      profile: { display_name: 'Synthetic owner', private: 'not projected' }, secret: 'not projected',
    };
    expect(projectLocalHome(payload)).toEqual({ status: 'ready', ideas: [], assets: [{ id: 'asset', name: 'Capability', description: 'Synthetic', revision: 1, egress_policy: 'local_only' }], profile: { displayName: 'Synthetic owner' } });
    expect(projectLocalHome(payload).assets).not.toBe(payload.assets);
  });
});
