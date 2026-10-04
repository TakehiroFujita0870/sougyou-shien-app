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
  expect(container.querySelector('h4')?.textContent).toBe('顧客と課題');
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

it('normalizes canonical chapters to H3 and keeps Markdown subheadings below them in source order', async () => {
  const chapterHeadings = [
    'エグゼクティブサマリー', 'ビジネスモデル', '顧客とマーケットサイズ', '収益モデル',
    '競争優位性', '実現可能性', 'リスク・撤退ライン', 'リスクミニマムなロードマップ',
  ];
  const markdown = [
    '# レポートタイトル',
    ...chapterHeadings.flatMap((heading, index) => [
      `${index % 2 === 0 ? '#' : '##'} ${heading}`,
      `第${index + 1}章本文`,
      ...(index === 0 ? ['## 小見出し', '小見出し本文', '### 詳細見出し', '詳細本文'] : []),
    ]),
  ].join('\n\n');
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  mounted = { root, container };
  await act(async () => root.render(<><h2>案のタイトル</h2><MarkdownReport markdown={markdown} chapterHeadings={chapterHeadings} /></>));

  const report = container.querySelector('.markdown-report');
  expect(report.querySelector('h3.markdown-report__title-heading')?.textContent).toBe('レポートタイトル');
  expect([...container.querySelectorAll('.markdown-report__chapter-heading')].map((heading) => [heading.tagName, heading.textContent])).toEqual([
    ...chapterHeadings.map((heading) => ['H3', heading]),
  ]);
  expect(report.querySelector('h4.markdown-report__subheading')?.textContent).toBe('小見出し');
  expect(report.querySelector('h5.markdown-report__subheading')?.textContent).toBe('詳細見出し');
  expect(report.querySelector('h1, h2')).toBeNull();
  expect([...report.querySelectorAll('h3, h4, h5, h6')].map((heading) => heading.textContent)).toEqual([
    'レポートタイトル', chapterHeadings[0], '小見出し', '詳細見出し', ...chapterHeadings.slice(1),
  ]);
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
