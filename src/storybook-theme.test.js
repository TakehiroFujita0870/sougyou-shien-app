import { readFile } from 'node:fs/promises';
import { describe, expect, it } from 'vitest';

describe('Storybook global theme entry', () => {
  it('loads the same global stylesheet and app-level desktop stories as the Vite entry', async () => {
    const [preview, appEntry, styles, stories] = await Promise.all([
      readFile(new URL('../.storybook/preview.jsx', import.meta.url), 'utf8'),
      readFile(new URL('./main.jsx', import.meta.url), 'utf8'),
      readFile(new URL('./styles.css', import.meta.url), 'utf8'),
      readFile(new URL('./App.stories.jsx', import.meta.url), 'utf8'),
    ]);

    expect(preview).toContain("import '../src/styles.css'");
    expect(appEntry).toContain("import './styles.css'");
    expect(preview).toContain('Dots-shell');
    expect(styles).toContain('@import "tailwindcss"');
    expect(styles).toContain('--color-canvas');
    expect(styles).toContain('--color-focus');
    for (const story of ['Home', 'Project', 'Knowledge', 'Account']) expect(stories).toContain(`export const ${story}`);
    expect(stories).toContain("width: '1440px'");
    expect(stories).toContain("height: '900px'");
  });
});
