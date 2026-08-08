import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

describe('mobile viewport entry point', () => {
  it('uses the device width instead of the browser default 980px layout viewport', () => {
    const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');

    expect(html).toMatch(/<meta\s+name=["']viewport["']\s+content=["']width=device-width,\s*initial-scale=1(?:\.0)?["']\s*\/?\s*>/i);
  });
});
