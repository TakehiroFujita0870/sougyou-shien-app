import { describe, expect, it } from 'vitest';
import { graphDepthForKind, nextGraphDepth, visibleAtGraphDepth, visibleGraphLink } from './localGraphDepth';

describe('local graph semantic depth', () => {
  it('places concepts in front and source evidence deeper in the scene', () => {
    expect(graphDepthForKind('idea')).toBe(0);
    expect(graphDepthForKind('asset')).toBe(0);
    expect(graphDepthForKind('source')).toBe(1);
    expect(graphDepthForKind('source_revision')).toBe(2);
    expect(graphDepthForKind('content_chunk')).toBe(3);
  });

  it('reveals adjacent depth layers and their edges as the user scrolls', () => {
    expect(visibleAtGraphDepth(0, 0)).toBe(true);
    expect(visibleAtGraphDepth(2, 0)).toBe(false);
    expect(visibleAtGraphDepth(2, 2)).toBe(true);
    expect(visibleAtGraphDepth(0, 2)).toBe(false);
    expect(visibleGraphLink({ depth: 1 }, { depth: 2 }, 2)).toBe(true);
    expect(visibleGraphLink({ depth: 0 }, { depth: 1 }, 2)).toBe(false);
    expect(nextGraphDepth(0, 80)).toBe(1);
    expect(nextGraphDepth(2, -80)).toBe(1);
    expect(nextGraphDepth(3, 80)).toBe(3);
  });
});
