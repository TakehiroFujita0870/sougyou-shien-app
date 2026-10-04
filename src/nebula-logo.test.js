import { readFileSync } from 'node:fs';
import { Window } from 'happy-dom';
import { describe, expect, it } from 'vitest';

describe('approved Nebula logo', () => {
  it('uses a compact transparent PNG for the ChatGPT host', () => {
    const png = readFileSync(new URL('../plugins/nebula/assets/nebula-icon.png', import.meta.url));
    expect(png.subarray(0, 8).toString('hex')).toBe('89504e470d0a1a0a');
    expect([png.readUInt32BE(16), png.readUInt32BE(20)]).toEqual([256, 256]);
    expect(png.length).toBeLessThan(10000);
    for (const path of ['../plugins/nebula/plugin.json', '../plugins/nebula/.codex-plugin/plugin.json']) {
      const manifest = JSON.parse(readFileSync(new URL(path, import.meta.url), 'utf8'));
      const presentation = manifest.extensions?.['com.openai'].interface ?? manifest.interface;
      expect(presentation.logo).toBe('./assets/nebula-icon.png');
      expect(presentation.composerIcon).toBe(presentation.logo);
    }
  });
  it('preserves the seven stars from concept 03 left without board decorations', () => {
    const svg = readFileSync(new URL('../public/assets/nebula-icon.svg', import.meta.url), 'utf8');
    expect(readFileSync(new URL('../plugins/nebula/assets/nebula-icon.svg', import.meta.url), 'utf8')).toBe(svg);
    const window = new Window();
    const doc = new window.DOMParser().parseFromString(svg, 'image/svg+xml');
    expect(doc.querySelector('svg').getAttribute('viewBox')).toBe('0 0 300 300');
    expect([...doc.querySelectorAll('circle')].map((star) =>
      ['cx', 'cy', 'r'].map((key) => Number(star.getAttribute(key))),
    )).toEqual([[81, 81, 15], [208, 63, 37.5], [150, 151, 38.5], [251, 147, 15], [62, 210, 34.5], [214, 223, 17], [131, 269, 15]]);
    expect([...doc.querySelectorAll('circle')].map((star) => star.getAttribute('fill')))
      .toEqual(['url(#blue)', 'url(#blue)', 'url(#ivory)', 'url(#amber)', 'url(#amber)', 'url(#blue)', 'url(#ivory)']);
    expect(doc.querySelector('script, image, foreignObject, text, ellipse, rect, line, path, filter')).toBeNull();
    expect(svg.length).toBeLessThan(2000);
  });
});
