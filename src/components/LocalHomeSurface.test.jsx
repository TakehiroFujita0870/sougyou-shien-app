// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, expect, it, vi } from 'vitest';
import { LocalHomeSurface } from './LocalHomeSurface';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let mounted;

afterEach(async () => {
  if (mounted) await act(async () => { mounted.root.unmount(); mounted.container.remove(); });
  mounted = null;
});

it('shows real idea cards, eight named viewpoints, asset profile, and a people placeholder', async () => {
  const client = { getHome: vi.fn(async () => ({
    status: 'ready',
    ideas: [{ id: 'idea-1', title: '名刺から協業', summary: '協業の候補を見つける', description: '本人のメモ' }],
    assets: [{ id: 'asset-1', name: '製造業経験', kind: 'experience', description: '現場での経験' }],
    profile: { displayName: 'Takehiro' },
  })) };
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  mounted = { root, container };
  await act(async () => root.render(<LocalHomeSurface client={client} />));

  expect(container.querySelectorAll('.local-home__idea-card')).toHaveLength(1);
  expect(container.textContent).toContain('名刺から協業');
  expect(container.textContent).toContain('本人のメモ');
  expect(container.textContent).toContain('7. リスクミニマムなロードマップ');
  expect(container.textContent).toContain('未整理');
  await act(async () => container.querySelector('[role="tab"][aria-selected="false"]').click());
  expect(container.textContent).toContain('Takehiro');
  expect(container.textContent).toContain('製造業経験');
  await act(async () => [...container.querySelectorAll('[role="tab"]')].find((node) => node.textContent === '人的ネットワーク').click());
  expect(container.textContent).toContain('今後実装予定');
  expect(container.textContent).not.toContain('名刺一覧');
});

it('shows a saved latest idea brief in its matching viewpoint', async () => {
  const sections = Array(8).fill('');
  sections[0] = '改訂済みの概要';
  sections[5] = '手持ちの技術で実装可能';
  const client = { getHome: vi.fn(async () => ({
    status: 'ready',
    ideas: [{ id: 'idea-1', title: '名刺から協業', summary: '古い概要', brief_revision: 2, brief_sections: sections }],
    assets: [],
    profile: null,
  })) };
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  mounted = { root, container };
  await act(async () => root.render(<LocalHomeSurface client={client} />));
  expect(container.textContent).toContain('改訂済みの概要');
  expect(container.textContent).toContain('5. 実現可能性');
  expect(container.textContent).toContain('手持ちの技術で実装可能');
  expect(container.textContent).not.toContain('古い概要');
  expect(container.textContent).toContain('未整理');
});

it('shows draft and unknown research states without inferring completion from a brief', async () => {
  const brief = Array(8).fill('');
  brief[0] = '保存された概要';
  const client = { getHome: vi.fn(async () => ({
    status: 'ready',
    ideas: [
      { id: 'idea-draft', title: '未調査案', summary: '', description: '', research_status: 'unresearched', brief_sections: brief },
      { id: 'idea-unknown', title: '状態不明案', summary: '', description: '', research_status: 'unknown', brief_sections: brief },
    ],
    assets: [],
    profile: null,
  })) };
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  mounted = { root, container };
  await act(async () => root.render(<LocalHomeSurface client={client} />));

  expect(container.textContent).toContain('未調査');
  expect(container.textContent).toContain('調査状態未確認');
  expect(container.textContent).toContain('保存された概要');
  expect(container.textContent).not.toContain('調査済み');
});

it('labels a server-validated researched idea in its card and detail', async () => {
  const client = { getHome: vi.fn(async () => ({
    status: 'ready', assets: [], profile: null,
    ideas: [{ id: 'researched', title: '調査した案', description: '下書き時点では調査未実施', research_status: 'researched', brief_sections: Array(8).fill('確認した概要') }],
  })) };
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  mounted = { root, container };
  await act(async () => root.render(<LocalHomeSurface client={client} />));
  expect(container.textContent.match(/調査済み/g)).toHaveLength(2);
  expect(container.textContent).not.toContain('調査状態未確認');
  expect(container.textContent).not.toContain('下書き時点では調査未実施');
  expect(container.textContent).toContain('確認した概要');
});

it('saves an explicit self-introduction edit and refreshes the Neo4j-backed view', async () => {
  let description = '元の紹介';
  const client = {
    getHome: vi.fn(async () => ({ status: 'ready', ideas: [], assets: [{ id: description === '元の紹介' ? 'asset-old' : 'asset-new', name: '自己紹介', kind: 'knowledge', description }], profile: null })),
    saveSelfIntroduction: vi.fn(async (value, id) => { expect(id).toBe('asset-old'); description = value; return 'asset-new'; }),
  };
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  mounted = { root, container };
  await act(async () => root.render(<LocalHomeSurface client={client} />));
  await act(async () => [...container.querySelectorAll('[role="tab"]')].find((node) => node.textContent === 'あなたのアセット').click());
  await act(async () => [...container.querySelectorAll('button')].find((node) => node.textContent === 'この画面で編集').click());
  await act(async () => {
    const textarea = container.querySelector('textarea');
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(textarea, '更新した紹介');
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await act(async () => container.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
  expect(client.saveSelfIntroduction).toHaveBeenCalledWith('更新した紹介', 'asset-old');
  expect(container.textContent).toContain('更新した紹介');
  expect(container.textContent).toContain('自己紹介を保存しました');
});
