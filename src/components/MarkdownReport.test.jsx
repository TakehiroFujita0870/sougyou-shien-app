// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import { MarkdownReport } from './MarkdownReport.jsx';

vi.mock('mermaid', () => ({ default: {
  initialize: vi.fn(),
  render: vi.fn(async () => ({ svg: '<svg xmlns="http://www.w3.org/2000/svg" onload="window.evil=true"><text>図の内容</text></svg>' })),
} }));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let mounted;
afterEach(async () => {
  if (mounted) await act(async () => { mounted.root.unmount(); mounted.container.remove(); });
  mounted = null;
});

it('shows Markdown tables, safe citations and public images without executing HTML or unsafe URLs', async () => {
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  mounted = { root, container };
  const markdown = [
    '## 顧客と課題',
    '| 顧客 | 課題 |\n| --- | --- |\n| 店舗 | 発注 |',
    '[公開出典](https://example.test/source)',
    '[危険なリンク](javascript:alert(1))',
    '![公開図](https://example.test/chart.png)',
    '![内部画像](http://localhost:8765/private.png)',
    '<script>window.evil = true</script>',
  ].join('\n\n');
  await act(async () => root.render(<MarkdownReport markdown={markdown} />));
  expect(container.querySelector('h2')?.textContent).toBe('顧客と課題');
  expect(container.querySelector('table')?.textContent).toContain('店舗');
  expect(container.querySelectorAll('a')).toHaveLength(1);
  expect(container.querySelector('a')?.getAttribute('href')).toBe('https://example.test/source');
  expect(container.querySelectorAll('img')).toHaveLength(1);
  expect(container.querySelector('img')?.getAttribute('referrerpolicy')).toBe('no-referrer');
  expect(container.querySelector('script')).toBeNull();
  expect(container.innerHTML).not.toContain('localhost:8765/private.png');
});

it('presents bare source URLs compactly without changing their destinations or authored labels', async () => {
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  mounted = { root, container };
  const bareUrl = 'https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/overview-plugins';
  const markdown = `資料: ${bareUrl}\n\n[Microsoft公式資料](${bareUrl})`;
  await act(async () => root.render(<MarkdownReport markdown={markdown} />));
  const links = [...container.querySelectorAll('a')];
  expect(links).toHaveLength(2);
  expect(links.map((link) => link.getAttribute('href'))).toEqual([bareUrl, bareUrl]);
  expect(links[0].textContent).toContain('learn.microsoft.com');
  expect(links[0].textContent).not.toContain('/en-us/microsoft-365/copilot/extensibility/');
  expect(links[0].getAttribute('title')).toBe(bareUrl);
  expect(links[1].textContent).toContain('Microsoft公式資料');
});

it('uses the same chapter style for canonical H1 and H2 headings', async () => {
  const chapterHeadings = ['エグゼクティブサマリー', 'ビジネスモデル'];
  const markdown = [
    '# レポートタイトル',
    `## ${chapterHeadings[0]}`,
    '概要本文',
    `# ${chapterHeadings[1]}`,
    '事業本文',
    '### 補足',
    '補足本文',
  ].join('\n\n');
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  mounted = { root, container };
  await act(async () => root.render(<MarkdownReport markdown={markdown} chapterHeadings={chapterHeadings} />));

  expect(container.querySelector('h1.markdown-report__title-heading')?.textContent).toBe('レポートタイトル');
  expect([...container.querySelectorAll('.markdown-report__chapter-heading')].map((heading) => [heading.tagName, heading.textContent])).toEqual([
    ['H2', chapterHeadings[0]], ['H1', chapterHeadings[1]],
  ]);
  expect(container.querySelector('h3.markdown-report__subheading')?.textContent).toBe('補足');
  expect(markdown).toContain(`# ${chapterHeadings[1]}`);
});

it('renders Mermaid diagrams as sanitized SVG', async () => {
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  mounted = { root, container };
  await act(async () => root.render(<MarkdownReport markdown={'```mermaid\ngraph LR\nA-->B\n```'} />));
  expect(container.querySelector('figure[aria-label="レポート内の図"]')?.textContent).toBe('図の内容');
  expect(container.innerHTML).not.toContain('onload');
});
