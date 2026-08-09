// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it } from 'vitest';
import { ProjectSurface } from './ProjectSurface';
import { demoProjectFixture } from './projectDemoFixtureAdapter';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let root;
let container;

afterEach(() => {
  if (root) act(() => root.unmount());
  container?.remove();
  root = undefined;
  container = undefined;
});

describe('ProjectSurface decision filter', () => {
  it.each([
    ['採用', '現場改善ミニ診断として深掘り'],
    ['保留', '初期価格の決定'],
    ['却下', '大規模な個別開発'],
  ])('%sを選ぶと該当する意思決定だけを表示する', async (kind, title) => {
    container = document.createElement('div');
    document.body.append(container);
    root = createRoot(container);
    await act(async () => {
      root.render(<ProjectSurface project={demoProjectFixture} conversationRepository={{ load: async () => [], save: async (messages) => messages }} />);
    });
    const select = container.querySelector('select[aria-label="表示する種類を選ぶ"]');
    await act(async () => {
      select.value = kind;
      select.dispatchEvent(new Event('change', { bubbles: true }));
    });
    expect([...container.querySelectorAll('[data-decision-kind]')]).toHaveLength(1);
    expect(container.querySelector('[data-decision-kind]').getAttribute('data-decision-kind')).toBe(kind);
    expect(container.textContent).toContain(title);
  });
});
