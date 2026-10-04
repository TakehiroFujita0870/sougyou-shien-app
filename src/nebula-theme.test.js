import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const shell = readFileSync(new URL('./components/LocalDashboardShell.css', import.meta.url), 'utf8');
const color = (name) => shell.match(new RegExp(`--${name}: (#[a-f0-9]{6});`))[1];
const luminance = (hex) => hex.slice(1).match(/../g).map((part) => {
  const value = parseInt(part, 16) / 255;
  return value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4;
}).reduce((sum, value, index) => sum + value * [.2126, .7152, .0722][index], 0);
const contrast = (a, b) => (Math.max(luminance(a), luminance(b)) + .05) / (Math.min(luminance(a), luminance(b)) + .05);

describe('shared Nebula theme', () => {
  it('keeps ivory text, secondary text and links readable on both card surfaces', () => {
    for (const foreground of ['color-text', 'color-text-muted', 'color-link']) {
      for (const background of ['color-surface', 'color-surface-raised']) {
        expect(contrast(color(foreground), color(background))).toBeGreaterThanOrEqual(4.5);
      }
    }
    expect(contrast(color('color-focus'), color('color-surface'))).toBeGreaterThanOrEqual(3);
  });
  it('self-hosts the rounded brand font and includes its redistribution license', () => {
    const styles = readFileSync(new URL('./styles.css', import.meta.url), 'utf8');
    expect(styles).toContain("url('/assets/fonts/quicksand-variable.ttf')");
    expect(shell).toContain("font-family: 'Nebula Rounded'");
    expect(readFileSync(new URL('../public/assets/fonts/quicksand-variable.ttf', import.meta.url)).readUInt32BE(0)).toBe(0x00010000);
    expect(readFileSync(new URL('../public/assets/fonts/OFL.txt', import.meta.url), 'utf8')).toContain('SIL OPEN FONT LICENSE');
  });
});
