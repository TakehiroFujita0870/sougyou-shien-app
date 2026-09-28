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

it('shows ideas, eight named viewpoints, common asset cards, and a people placeholder', async () => {
  const client = { getHome: vi.fn(async () => ({
    status: 'ready',
    ideas: [{ id: 'idea-1', title: '名刺から協業', summary: '協業の候補を見つける', description: '本人のメモ' }],
    assets: [
      { id: 'asset-1', name: '自己紹介', kind: 'knowledge', description: '現場での経験', revision: 1 },
      { id: 'asset-2', name: '製造業の経験', kind: 'experience', description: '品質管理を担当', revision: 1 },
    ],
    profile: { displayName: '非表示にするプロフィール' },
  })) };
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  mounted = { root, container };
  await act(async () => root.render(<LocalHomeSurface client={client} />));

  const tabIcons = [...container.querySelectorAll('[role="tab"] svg[aria-hidden="true"]')];
  expect(tabIcons).toHaveLength(3);
  expect(tabIcons.map((icon) => icon.getAttribute('stroke-width'))).toEqual(['1.8', '1.8', '1.8']);
  expect(tabIcons.map((icon) => icon.getAttribute('width'))).toEqual(['18', '18', '18']);
  expect(tabIcons.map((icon) => icon.getAttribute('viewBox'))).toEqual(['0 0 24 24', '0 0 24 24', '0 0 24 24']);
  expect(container.querySelectorAll('.local-home__idea-card')).toHaveLength(1);
  expect(container.textContent).toContain('名刺から協業');
  expect(container.textContent).toContain('本人のメモ');
  expect(container.textContent).toContain('リスクミニマムなロードマップ');
  expect(container.textContent).not.toContain('7. リスクミニマムなロードマップ');
  expect(container.textContent).toContain('未整理');
  await act(async () => container.querySelector('[role="tab"][aria-selected="false"]').click());
  expect(container.querySelectorAll('.local-home__asset-card')).toHaveLength(2);
  expect(container.textContent).toContain('自己紹介');
  expect(container.textContent).toContain('製造業の経験');
  expect(container.textContent).toContain('品質管理を担当');
  expect(container.textContent).not.toContain('非表示にするプロフィール');
  expect(container.textContent).not.toContain('保有している資産');
  expect(container.textContent).not.toContain('ABOUT YOU');
  expect(container.textContent).not.toContain('experience');
  expect(container.textContent).not.toContain('knowledge');
  expect(container.querySelectorAll('.local-home__asset-card button[aria-label^="編集"]')).toHaveLength(2);
  await act(async () => [...container.querySelectorAll('[role="tab"]')].find((node) => node.textContent === '人的ネットワーク').click());
  expect(container.textContent).toContain('今後実装予定');
  expect(container.textContent).not.toContain('名刺一覧');
});

it('separates strengths and barriers into editable columns', async () => {
  const client = { getHome: vi.fn(async () => ({ status: 'ready', ideas: [], assets: [
    { id: 'strength', name: '製造現場の経験', kind: 'experience', description: '改善経験', revision: 1 },
    { id: 'barrier', name: '販売への迷い', kind: 'barrier', description: '顧客開拓が不安', revision: 1 },
  ], profile: null })) };
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  mounted = { root, container };
  await act(async () => root.render(<LocalHomeSurface client={client} />));
  await act(async () => [...container.querySelectorAll('[role="tab"]')].find((tab) => tab.textContent === 'あなたのアセット').click());
  const columns = container.querySelectorAll('.local-home__asset-list');
  expect(columns).toHaveLength(2);
  expect(columns[0].querySelector('h2').textContent).toContain('強み・経験');
  expect(columns[0].textContent).toContain('製造現場の経験');
  expect(columns[0].textContent).not.toContain('販売への迷い');
  expect(columns[1].querySelector('h2').textContent).toContain('弱み・迷い');
  expect(columns[1].textContent).toContain('販売への迷い');
  expect(columns[1].querySelectorAll('button[aria-label^="編集"], button[aria-label^="削除"]')).toHaveLength(2);
});

it('navigates cards by keyboard and persists cross-column moves', async () => {
  const first = { id: 'first', name: '経験A', kind: 'asset', description: '内容A', revision: 1 };
  const second = { id: 'second', name: '経験B', kind: 'asset', description: '内容B', revision: 1 };
  const moved = { ...second, id: 'moved', kind: 'barrier', revision: 2 };
  const client = {
    getHome: vi.fn().mockResolvedValueOnce({ status: 'ready', ideas: [], assets: [first, second], profile: null })
      .mockResolvedValueOnce({ status: 'ready', ideas: [], assets: [first, moved], profile: null }),
    saveAsset: vi.fn().mockResolvedValue({ id: moved.id, revision: moved.revision }),
  };
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  mounted = { root, container };
  await act(async () => root.render(<LocalHomeSurface client={client} />));
  await act(async () => [...container.querySelectorAll('[role="tab"]')].find((tab) => tab.textContent === 'あなたのアセット').click());
  const card = container.querySelector('[data-asset-id="first"]');
  card.focus();
  await act(async () => card.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true })));
  expect(document.activeElement.dataset.assetId).toBe('second');
  await act(async () => document.activeElement.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', altKey: true, bubbles: true })));
  expect(client.saveAsset).toHaveBeenCalledWith('second', { name: '経験B', description: '内容B', expectedRevision: 1, kind: 'barrier' });
  expect(container.querySelector('[data-asset-column="barrier"] [data-asset-id="moved"]')).not.toBeNull();
  expect(document.activeElement.dataset.assetId).toBe('moved');
});

it('accepts a card drop into the other column and keeps the original on save failure', async () => {
  const asset = { id: 'first', name: '現場経験', kind: 'asset', description: '改善', revision: 1 };
  const client = { getHome: vi.fn().mockResolvedValue({ status: 'ready', ideas: [], assets: [asset], profile: null }),
    saveAsset: vi.fn().mockRejectedValue({ kind: 'unavailable' }) };
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  mounted = { root, container };
  await act(async () => root.render(<LocalHomeSurface client={client} />));
  await act(async () => [...container.querySelectorAll('[role="tab"]')].find((tab) => tab.textContent === 'あなたのアセット').click());
  const transfer = { setData: vi.fn(), effectAllowed: '', dropEffect: '' };
  const drag = (node, type) => { const event = new Event(type, { bubbles: true, cancelable: true }); Object.defineProperty(event, 'dataTransfer', { value: transfer }); node.dispatchEvent(event); };
  await act(async () => drag(container.querySelector('[data-asset-id="first"]'), 'dragstart'));
  const target = container.querySelector('[data-asset-column="barrier"]');
  await act(async () => drag(target, 'dragover'));
  expect(target.dataset.dropActive).toBe('true');
  await act(async () => drag(target, 'drop'));
  expect(client.saveAsset).toHaveBeenCalledWith('first', { name: '現場経験', description: '改善', expectedRevision: 1, kind: 'barrier' });
  expect(container.querySelector('[data-asset-column="strength"] [data-asset-id="first"]')).not.toBeNull();
  expect(container.textContent).toContain('元の欄に残しています');
});

it('keeps card shortcuts out of text input and offers editing and delete confirmation', async () => {
  const asset = { id: 'one', name: '試験用の強み', kind: 'asset', description: '入力内容', revision: 1 };
  const client = { getHome: vi.fn().mockResolvedValue({ status: 'ready', ideas: [], assets: [asset], profile: null }), saveAsset: vi.fn() };
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  mounted = { root, container };
  await act(async () => root.render(<LocalHomeSurface client={client} />));
  await act(async () => [...container.querySelectorAll('[role="tab"]')].find((tab) => tab.textContent === 'あなたのアセット').click());
  const card = container.querySelector('[data-asset-id="one"]');
  card.focus();
  await act(async () => card.dispatchEvent(new KeyboardEvent('keydown', { key: '?', bubbles: true })));
  expect(container.textContent).toContain('Alt＋→');
  await act(async () => card.dispatchEvent(new KeyboardEvent('keydown', { key: 'e', bubbles: true })));
  const field = container.querySelector('textarea[name="title"]');
  expect(document.activeElement).toBe(field);
  await act(async () => field.dispatchEvent(new KeyboardEvent('keydown', { key: 'Delete', bubbles: true })));
  expect(container.querySelector('[role="alertdialog"]')).toBeNull();
  await act(async () => field.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })));
  expect(container.querySelector('textarea[name="title"]')).toBeNull();
  expect(document.activeElement).toBe(card);
  await act(async () => card.dispatchEvent(new KeyboardEvent('keydown', { key: 'Delete', bubbles: true })));
  expect(container.querySelector('[role="alertdialog"]')).not.toBeNull();
  expect(client.saveAsset).not.toHaveBeenCalled();
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
  expect(container.textContent).toContain('実現可能性');
  expect(container.textContent).not.toContain('5. 実現可能性');
  expect(container.textContent).toContain('手持ちの技術で実装可能');
  expect(container.textContent).not.toContain('古い概要');
  expect(container.textContent).toContain('未整理');
});

it('prefers the saved Markdown report over duplicate section text and keeps cited sources', async () => {
  const client = { getHome: vi.fn(async () => ({
    status: 'ready', assets: [], profile: null,
    ideas: [{ id: 'idea-1', title: '新事業', summary: '', description: '', research_status: 'researched',
      brief_sections: Array(8).fill('検索用の章'), report_markdown: '## 顧客\n\n| 層 | 課題 |\n| --- | --- |\n| 店舗 | 発注 |',
      brief_citations: [[{ url: 'https://example.test/source', title: '公開資料' }], ...Array.from({ length: 7 }, () => [])],
    }],
  })) };
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  mounted = { root, container };
  await act(async () => root.render(<LocalHomeSurface client={client} />));
  expect(container.querySelector('.markdown-report table')?.textContent).toContain('店舗');
  expect(container.textContent).not.toContain('検索用の章');
  expect(container.querySelector('.local-home__citation a')?.getAttribute('href')).toBe('https://example.test/source');
  expect(container.querySelector('.local-home__detail-status-row .local-home__status-badge')?.textContent).toBe('調査済み');
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
  expect(container.querySelectorAll('.local-home__status-badge')).toHaveLength(1);
  await act(async () => [...container.querySelectorAll('.local-home__idea-select')].find((button) => button.textContent.includes('状態不明案')).click());
  expect(container.querySelector('.local-home__detail-status-row')).toBeNull();
  expect(container.textContent).toContain('保存された概要');
  expect(container.textContent).not.toContain('調査済み');
});

it('keeps only titles in the idea list and a two-state badge at the right of the detail', async () => {
  const client = { getHome: vi.fn(async () => ({
    status: 'ready', assets: [], profile: null,
    ideas: [
      { id: 'draft', title: '非常に長い題名でも状態を横に残せるアイデア', research_status: 'unresearched' },
      { id: 'researched', title: '正式調査済み', research_status: 'researched' },
      { id: 'imported', title: '以前の調査を取り込んだ案', research_status: 'prior_research_import' },
    ],
  })) };
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  mounted = { root, container };
  await act(async () => root.render(<LocalHomeSurface client={client} />));

  const cards = [...container.querySelectorAll('.local-home__idea-card')];
  expect(cards).toHaveLength(3);
  for (const card of cards) {
    expect(card.querySelector('.local-home__idea-heading')).not.toBeNull();
    expect(card.querySelector('.local-home__status-badge')).toBeNull();
    expect(card.querySelector('.local-home__idea-summary')).toBeNull();
  }
  expect(container.querySelector('.local-home__detail-status-row .local-home__status-badge').textContent).toBe('未調査');
  expect(container.querySelector('.local-home__status-badge').getAttribute('data-research-state')).toBe('unresearched');
  await act(async () => cards[2].querySelector('button').click());
  expect(container.querySelector('.local-home__detail-status-row .local-home__status-badge').textContent).toBe('調査済み');
  expect(cards[2].textContent).not.toContain('ResearchRun');
  expect(container.textContent).not.toContain('過去調査を取り込みました');
});

it('places asset editing in a small, keyboard-reachable icon button at the card corner', async () => {
  const client = { getHome: vi.fn(async () => ({
    status: 'ready', ideas: [], profile: null,
    assets: [{ id: 'asset-1', name: '経験', description: '内容', revision: 1 }],
  })) };
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  mounted = { root, container };
  await act(async () => root.render(<LocalHomeSurface client={client} />));
  await act(async () => [...container.querySelectorAll('[role="tab"]')].find((node) => node.textContent === 'あなたのアセット').click());

  const editButton = container.querySelector('.local-home__icon-button[aria-label="編集: 経験"]');
  expect(editButton).not.toBeNull();
  expect(editButton.querySelector('svg[aria-hidden="true"]')).not.toBeNull();
  expect(editButton.textContent).not.toContain('編集');
  expect(editButton.getAttribute('type')).toBe('button');
});

it('edits the selected idea title in the detail without losing its brief', async () => {
  const original = { id: 'idea-original', title: '元の題名', description: '元の説明', summary: '', revision: 0, research_status: 'researched', brief_sections: ['調査済み概要', ...Array(7).fill('')] };
  const revised = { ...original, id: 'idea-revised', title: '更新した題名', revision: 1 };
  const client = {
    getHome: vi.fn().mockResolvedValueOnce({ status: 'ready', ideas: [original], assets: [], profile: null })
      .mockResolvedValueOnce({ status: 'ready', ideas: [revised], assets: [], profile: null }),
    saveIdea: vi.fn().mockResolvedValue({ id: 'idea-revised', revision: 1 }),
  };
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  mounted = { root, container };
  await act(async () => root.render(<LocalHomeSurface client={client} />));
  await act(async () => container.querySelector('button[aria-label="編集: 元の題名"]').click());
  expect(container.textContent).toContain('題名だけの変更は調査結果を引き継ぎます');
  const title = container.querySelector('#idea-edit-title');
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(title, '更新した題名');
    title.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await act(async () => container.querySelector('.local-home__idea-edit-form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
  expect(client.saveIdea).toHaveBeenCalledWith('idea-original', { title: '更新した題名', description: '元の説明', expectedRevision: 0 });
  expect(container.querySelector('#selected-idea-heading').textContent).toBe('更新した題名');
  expect(container.textContent).toContain('調査済み概要');
});

it('keeps idea actions only in the selected detail and requires confirmation before archiving', async () => {
  const ideas = [
    { id: 'idea-1', title: '選択中の案', summary: '', description: '', revision: 0 },
    { id: 'idea-2', title: '整理する案', summary: '', description: '', revision: 4 },
  ];
  const client = {
    getHome: vi.fn().mockResolvedValueOnce({ status: 'ready', ideas, assets: [], profile: null })
      .mockResolvedValueOnce({ status: 'ready', ideas: [ideas[0]], assets: [], profile: null }),
    archiveRecord: vi.fn().mockResolvedValue({ id: 'idea-2', revision: 5, replayed: false }),
  };
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  mounted = { root, container };
  await act(async () => root.render(<LocalHomeSurface client={client} />));

  expect(container.querySelector('.local-home__idea-card .local-home__card-actions')).toBeNull();
  await act(async () => [...container.querySelectorAll('.local-home__idea-select')][1].click());
  const deleteButton = container.querySelector('button[aria-label="削除: 整理する案"]');
  expect(container.querySelector('.local-home__detail-header button[aria-label="編集: 整理する案"]')).not.toBeNull();
  expect(deleteButton.disabled).toBe(false);
  await act(async () => deleteButton.click());
  expect(container.querySelector('[role="alertdialog"]')?.textContent).toContain('「整理する案」を削除しますか？');
  expect(container.querySelector('[aria-pressed="true"] strong').textContent).toBe('整理する案');
  expect(client.archiveRecord).not.toHaveBeenCalled();
  await act(async () => [...container.querySelectorAll('[role="alertdialog"] button')].find((button) => button.textContent === 'キャンセル').click());
  expect(client.archiveRecord).not.toHaveBeenCalled();

  await act(async () => container.querySelector('button[aria-label="削除: 整理する案"]').click());
  await act(async () => [...container.querySelectorAll('[role="alertdialog"] button')].find((button) => button.textContent === '削除する').click());
  expect(client.archiveRecord).toHaveBeenCalledWith('idea', 'idea-2', 4, { signal: expect.any(AbortSignal) });
  expect(client.getHome).toHaveBeenCalledTimes(2);
  expect(container.querySelectorAll('.local-home__idea-card')).toHaveLength(1);
  expect(container.textContent).toContain('整理する案を削除しました');
});

it('keeps confirmation available after a recoverable failure and allows the same intent to be retried', async () => {
  const idea = { id: 'idea-1', title: '再試行する案', summary: '', description: '', revision: 2 };
  const client = {
    getHome: vi.fn().mockResolvedValueOnce({ status: 'ready', ideas: [idea], assets: [], profile: null })
      .mockResolvedValueOnce({ status: 'empty', ideas: [], assets: [], profile: null }),
    archiveRecord: vi.fn().mockRejectedValueOnce({ kind: 'unavailable' })
      .mockResolvedValueOnce({ id: 'idea-1', revision: 3, replayed: true }),
  };
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  mounted = { root, container };
  await act(async () => root.render(<LocalHomeSurface client={client} />));
  await act(async () => container.querySelector('button[aria-label="削除: 再試行する案"]').click());
  const confirm = () => container.querySelector('[role="alertdialog"] button:last-child');
  await act(async () => confirm().click());
  expect(container.querySelector('[role="alertdialog"]')).not.toBeNull();
  expect(container.querySelector('[role="alert"]')?.textContent).toContain('削除できませんでした');

  await act(async () => confirm().click());
  expect(client.archiveRecord).toHaveBeenCalledTimes(2);
  expect(client.archiveRecord.mock.calls[0].slice(0, 3)).toEqual(client.archiveRecord.mock.calls[1].slice(0, 3));
  expect(container.querySelector('[role="alertdialog"]')).toBeNull();
  expect(container.querySelectorAll('.local-home__idea-card')).toHaveLength(0);
});

it('moves focus into deletion confirmation, supports Escape, and disables all delete controls while pending', async () => {
  let finishArchive;
  const idea = { id: 'idea-1', title: '確認する案', summary: '', description: '', revision: 1 };
  const asset = { id: 'asset-1', name: '確認する資料', description: '', revision: 1 };
  const client = {
    getHome: vi.fn().mockResolvedValueOnce({ status: 'ready', ideas: [idea], assets: [asset], profile: null })
      .mockResolvedValueOnce({ status: 'ready', ideas: [], assets: [asset], profile: null }),
    archiveRecord: vi.fn(() => new Promise((resolve) => { finishArchive = resolve; })),
  };
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  mounted = { root, container };
  await act(async () => root.render(<LocalHomeSurface client={client} />));

  const trigger = container.querySelector('button[aria-label="削除: 確認する案"]');
  await act(async () => trigger.click());
  expect(document.activeElement.textContent).toBe('削除する');
  await act(async () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })));
  expect(container.querySelector('[role="alertdialog"]')).toBeNull();
  expect(document.activeElement).toBe(trigger);
  expect(client.archiveRecord).not.toHaveBeenCalled();

  await act(async () => trigger.click());
  await act(async () => container.querySelector('[role="alertdialog"] button:last-child').click());
  expect(document.activeElement).toBe(container.querySelector('[role="alertdialog"]'));
  await act(async () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true })));
  expect(document.activeElement).toBe(container.querySelector('[role="alertdialog"]'));
  expect([...container.querySelectorAll('button[aria-label^="削除:"]')].every((button) => button.disabled)).toBe(true);
  expect([...container.querySelectorAll('[role="alertdialog"] button')].every((button) => button.disabled)).toBe(true);
  await act(async () => finishArchive({ id: 'idea-1', revision: 2, replayed: false }));
  expect(container.querySelector('[role="alertdialog"]')).toBeNull();
  expect(container.querySelectorAll('.local-home__idea-card')).toHaveLength(0);
});

it('clears an aborted deletion confirmation and pending state when the client changes', async () => {
  let finishArchive;
  let archiveSignal;
  const idea = { id: 'idea-1', title: '再読込する案', summary: '', description: '', revision: 1 };
  const firstClient = {
    getHome: vi.fn(async () => ({ status: 'ready', ideas: [idea], assets: [], profile: null })),
    archiveRecord: vi.fn((kind, id, revision, { signal }) => {
      archiveSignal = signal;
      return new Promise((resolve) => { finishArchive = resolve; });
    }),
  };
  const nextClient = { getHome: vi.fn(async () => ({ status: 'ready', ideas: [idea], assets: [], profile: null })) };
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  mounted = { root, container };
  await act(async () => root.render(<LocalHomeSurface client={firstClient} />));
  await act(async () => container.querySelector('button[aria-label="削除: 再読込する案"]').click());
  await act(async () => container.querySelector('[role="alertdialog"] button:last-child').click());
  expect(container.querySelector('[role="alertdialog"] button:last-child').textContent).toBe('削除中…');

  await act(async () => root.render(<LocalHomeSurface client={nextClient} />));
  expect(archiveSignal.aborted).toBe(true);
  expect(container.querySelector('[role="alertdialog"]')).toBeNull();
  expect(container.querySelector('button[aria-label="削除: 再読込する案"]').disabled).toBe(false);
  await act(async () => finishArchive({ id: 'idea-1', revision: 2, replayed: false }));
  expect(container.querySelectorAll('.local-home__idea-card')).toHaveLength(1);
  expect(container.querySelector('[role="alertdialog"]')).toBeNull();
});

it('aborts a pending deletion when the home surface unmounts', async () => {
  let archiveSignal;
  let finishArchive;
  const idea = { id: 'idea-1', title: '離脱する案', summary: '', description: '', revision: 1 };
  const client = {
    getHome: vi.fn(async () => ({ status: 'ready', ideas: [idea], assets: [], profile: null })),
    archiveRecord: vi.fn((_kind, _id, _revision, { signal }) => {
      archiveSignal = signal;
      return new Promise((resolve) => { finishArchive = resolve; });
    }),
  };
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  mounted = { root, container };
  await act(async () => root.render(<LocalHomeSurface client={client} />));
  await act(async () => container.querySelector('button[aria-label="削除: 離脱する案"]').click());
  await act(async () => container.querySelector('[role="alertdialog"] button:last-child').click());
  expect(archiveSignal.aborted).toBe(false);

  await act(async () => root.unmount());
  expect(archiveSignal.aborted).toBe(true);
  mounted = null;
  container.remove();
  await act(async () => finishArchive({ id: 'archived-tip', revision: 2 }));
  expect(client.getHome).toHaveBeenCalledTimes(1);
});

it('offers a home reload when the archive succeeds but its follow-up read fails', async () => {
  const idea = { id: 'idea-1', title: '再読み込みが必要な案', summary: '', description: '', revision: 1 };
  const client = {
    getHome: vi.fn().mockResolvedValueOnce({ status: 'ready', ideas: [idea], assets: [], profile: null })
      .mockRejectedValueOnce(new Error('temporary read failure'))
      .mockResolvedValueOnce({ status: 'empty', ideas: [], assets: [], profile: null }),
    archiveRecord: vi.fn().mockResolvedValue({ id: 'idea-1', revision: 2, replayed: false }),
  };
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  mounted = { root, container };
  await act(async () => root.render(<LocalHomeSurface client={client} />));
  await act(async () => container.querySelector('button[aria-label="削除: 再読み込みが必要な案"]').click());
  await act(async () => container.querySelector('[role="alertdialog"] button:last-child').click());
  expect(container.textContent).toContain('再読み込みが必要な案を削除しました。一覧を更新できませんでした');
  await act(async () => [...container.querySelectorAll('button')].find((button) => button.textContent === 'ホームを再読み込み').click());
  expect(client.getHome).toHaveBeenCalledTimes(3);
  expect(container.querySelectorAll('.local-home__idea-card')).toHaveLength(0);
  expect(container.textContent).not.toContain('一覧を更新できませんでした');
});

it('refreshes a stale revision after a conflict and disables deletion when revision is unavailable', async () => {
  const stale = { id: 'idea-1', title: '更新される案', summary: '', description: '', revision: 0 };
  const current = { ...stale, revision: 1 };
  const missingRevision = { id: 'idea-2', title: '版が不明な案', summary: '', description: '' };
  const client = {
    getHome: vi.fn().mockResolvedValueOnce({ status: 'ready', ideas: [stale, missingRevision], assets: [], profile: null })
      .mockResolvedValueOnce({ status: 'ready', ideas: [current, missingRevision], assets: [], profile: null })
      .mockResolvedValueOnce({ status: 'ready', ideas: [missingRevision], assets: [], profile: null }),
    archiveRecord: vi.fn().mockRejectedValueOnce({ kind: 'conflict' })
      .mockResolvedValueOnce({ id: 'idea-1', revision: 2, replayed: false }),
  };
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  mounted = { root, container };
  await act(async () => root.render(<LocalHomeSurface client={client} />));

  const unavailableDelete = container.querySelector('button[aria-label="削除: 版が不明な案"]');
  expect(unavailableDelete).toBeNull();
  await act(async () => [...container.querySelectorAll('.local-home__idea-select')][1].click());
  expect(container.querySelector('button[aria-label="削除: 版が不明な案"]').disabled).toBe(true);
  await act(async () => [...container.querySelectorAll('.local-home__idea-select')][0].click());
  await act(async () => container.querySelector('button[aria-label="削除: 更新される案"]').click());
  await act(async () => container.querySelector('[role="alertdialog"] button:last-child').click());
  expect(client.getHome).toHaveBeenCalledTimes(2);
  expect(container.querySelector('[role="alertdialog"]')).toBeNull();
  expect(container.textContent).toContain('最新の一覧を読み込みました');

  await act(async () => container.querySelector('button[aria-label="削除: 更新される案"]').click());
  await act(async () => container.querySelector('[role="alertdialog"] button:last-child').click());
  expect(client.archiveRecord.mock.calls.map((call) => call.slice(0, 3))).toEqual([
    ['idea', 'idea-1', 0],
    ['idea', 'idea-1', 1],
  ]);
});

it('archives an asset with its current revision and leaves items without a safe revision disabled', async () => {
  const asset = { id: 'asset-1', name: '整理するアセット', kind: 'knowledge', description: '記録内容', revision: 3 };
  const invalidAsset = { id: 'asset-2', name: '版が不明', kind: 'knowledge', description: '', revision: 0 };
  const client = {
    getHome: vi.fn().mockResolvedValueOnce({ status: 'ready', ideas: [], assets: [asset, invalidAsset], profile: null })
      .mockResolvedValueOnce({ status: 'empty', ideas: [], assets: [], profile: null }),
    archiveRecord: vi.fn().mockResolvedValue({ id: asset.id, revision: 4, replayed: false }),
  };
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  mounted = { root, container };
  await act(async () => root.render(<LocalHomeSurface client={client} />));
  await act(async () => [...container.querySelectorAll('[role="tab"]')].find((tab) => tab.textContent.includes('アセット')).click());

  expect(container.querySelector('button[aria-label="削除: 版が不明"]').disabled).toBe(true);
  await act(async () => container.querySelector('button[aria-label="削除: 整理するアセット"]').click());
  await act(async () => container.querySelector('[role="alertdialog"] button:last-child').click());
  expect(client.archiveRecord).toHaveBeenCalledWith('asset', asset.id, 3, { signal: expect.any(AbortSignal) });
  expect(container.querySelectorAll('.local-home__asset-card')).toHaveLength(0);
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
  expect(container.textContent.match(/調査済み/g)).toHaveLength(1);
  expect(container.textContent).not.toContain('調査状態未確認');
  expect(container.textContent).not.toContain('下書き時点では調査未実施');
  expect(container.textContent).toContain('確認した概要');
});

it('distinguishes completed research with missing current sources from drafts and cited research', async () => {
  const client = { getHome: vi.fn(async () => ({
    status: 'ready', assets: [], profile: null,
    ideas: [{ id: 'missing-sources', title: '出典が未完了の案', research_status: 'research_sources_missing', brief_sections: Array(8).fill('保存された調査概要'), brief_citations: Array.from({ length: 8 }, () => []) }],
  })) };
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  mounted = { root, container };
  await act(async () => root.render(<LocalHomeSurface client={client} />));
  expect(container.textContent).not.toContain('調査済み・出典を表示できません');
  expect(container.querySelector('.local-home__status-badge').textContent).toBe('調査済み');
  expect(container.querySelector('.local-home__status-badge').getAttribute('data-research-state')).toBe('research_sources_missing');
  expect(container.textContent).not.toContain('未調査');
  expect(container.textContent).not.toContain('調査状態未確認');
  expect(container.textContent).toContain('保存された調査概要');
  expect(container.querySelectorAll('.local-home__citation')).toHaveLength(0);
});

it('uses the same researched badge for imported research while retaining citation detail', async () => {
  const client = { getHome: vi.fn(async () => ({
    status: 'ready', assets: [], profile: null,
    ideas: [
      { id: 'imported', title: '過去調査', research_status: 'prior_research_import', brief_origin: 'prior_research_import', brief_sections: Array(8).fill('過去に確認した概要'), brief_citations: [[{ url: 'https://example.test/source', title: '公開出典' }], ...Array.from({ length: 7 }, () => [])] },
      { id: 'imported-missing', title: '出典不足の過去調査', research_status: 'prior_research_sources_missing', brief_origin: 'prior_research_import', brief_sections: Array(8).fill('過去に確認した概要'), brief_citations: Array.from({ length: 8 }, () => []) },
    ],
  })) };
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  mounted = { root, container };
  await act(async () => root.render(<LocalHomeSurface client={client} />));
  expect(container.textContent).not.toContain('過去調査を取り込みました');
  expect([...container.querySelectorAll('.local-home__status-badge')].map((badge) => badge.textContent)).toEqual(['調査済み']);
  expect(container.querySelectorAll('.local-home__status-badge[data-research-state^="prior_research"]')).toHaveLength(1);
  expect(container.textContent).not.toContain('未調査');
  expect([...container.querySelectorAll('.local-home__citation a')].map((link) => link.textContent)).toContain('公開出典 ↗');
});

it('edits title and content through the same form for any asset and supports cancel', async () => {
  const assets = [
    { id: 'asset-1', name: '経験', kind: 'experience', description: '内容1', revision: 1 },
    { id: 'asset-2', name: '資料', kind: 'document', description: '内容2', revision: 1 },
    { id: 'asset-3', name: '営業への迷い', kind: 'barrier', description: '最初の顧客への声かけが不安', revision: 1 },
  ];
  const client = { getHome: vi.fn(async () => ({ status: 'ready', ideas: [], assets, profile: null })) };
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  mounted = { root, container };
  await act(async () => root.render(<LocalHomeSurface client={client} />));
  await act(async () => [...container.querySelectorAll('[role="tab"]')].find((node) => node.textContent === 'あなたのアセット').click());

  for (const asset of assets) {
    await act(async () => [...container.querySelectorAll('.local-home__asset-card')].find((card) => card.textContent.includes(asset.name)).querySelector('button').click());
    expect(container.querySelector('textarea[name="title"]').value).toBe(asset.name);
    expect(container.querySelector('textarea[name="content"]').value).toBe(asset.description);
    expect(container.textContent).not.toContain(asset.kind);
    await act(async () => [...container.querySelectorAll('button')].find((node) => node.textContent === 'キャンセル').click());
  }
  expect(container.querySelectorAll('.local-home__asset-card')).toHaveLength(3);
});

it('saves a changed asset title and content then refreshes to the successor record', async () => {
  const original = { id: 'asset-current', name: '元の題名', kind: 'document', description: '元の内容', revision: 4, egress_policy: 'local_only' };
  const successor = { ...original, id: 'asset-successor', name: '更新した題名', description: '更新した内容', revision: 5 };
  const client = {
    getHome: vi.fn().mockResolvedValueOnce({ status: 'ready', ideas: [], assets: [original], profile: null })
      .mockResolvedValueOnce({ status: 'ready', ideas: [], assets: [successor], profile: null }),
    saveAsset: vi.fn().mockResolvedValue({ id: successor.id, revision: successor.revision }),
  };
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  mounted = { root, container };
  await act(async () => root.render(<LocalHomeSurface client={client} />));
  await act(async () => [...container.querySelectorAll('[role="tab"]')].find((node) => node.textContent === 'あなたのアセット').click());
  await act(async () => container.querySelector('button[aria-label="編集: 元の題名"]').click());
  const setTextArea = async (name, value) => act(async () => {
    const field = container.querySelector(`textarea[name="${name}"]`);
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(field, value);
    field.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await setTextArea('title', '更新した題名');
  await setTextArea('content', '更新した内容');
  await act(async () => container.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));

  expect(client.saveAsset).toHaveBeenCalledWith('asset-current', { name: '更新した題名', description: '更新した内容', expectedRevision: 4 });
  expect(client.getHome).toHaveBeenCalledTimes(2);
  expect(container.textContent).toContain('更新した題名');
  expect(container.textContent).toContain('更新した内容');
  expect(container.textContent).toContain('変更を保存しました');
  expect(container.querySelectorAll('.local-home__asset-card')).toHaveLength(1);
});

it('preserves asset drafts after save conflicts and generic failures', async () => {
  const asset = { id: 'asset-1', name: '元題名', kind: 'knowledge', description: '元内容', revision: 2, egress_policy: 'shareable' };
  for (const error of [{ kind: 'conflict' }, { kind: 'unavailable' }]) {
    const client = {
      getHome: vi.fn().mockResolvedValue({ status: 'ready', ideas: [], assets: [asset], profile: null }),
      saveAsset: vi.fn().mockRejectedValue(error),
    };
    const container = document.createElement('div');
    document.body.append(container);
    const root = createRoot(container);
    mounted = { root, container };
    await act(async () => root.render(<LocalHomeSurface client={client} />));
    await act(async () => [...container.querySelectorAll('[role="tab"]')].find((node) => node.textContent === 'あなたのアセット').click());
    await act(async () => container.querySelector('button[aria-label="編集: 元題名"]').click());
    const title = container.querySelector('textarea[name="title"]');
    const content = container.querySelector('textarea[name="content"]');
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(title, '手元の変更');
      title.dispatchEvent(new Event('input', { bubbles: true }));
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(content, '編集した内容');
      content.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => container.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
    expect(container.querySelector('textarea[name="title"]').value).toBe('手元の変更');
    expect(container.querySelector('textarea[name="content"]').value).toBe('編集した内容');
    expect(container.querySelector('[role="alert"]').textContent).toContain(error.kind === 'conflict' ? '別の更新' : '入力内容は残っています');
    expect(client.getHome).toHaveBeenCalledTimes(1);
    await act(async () => { root.unmount(); container.remove(); });
    mounted = null;
  }
});

it('shows only valid HTTP source links beside the matching brief viewpoint', async () => {
  const citations = Array.from({ length: 8 }, () => []);
  citations[1] = [
    { title: '公開統計', url: 'https://example.com/statistics?id=1#section', source_id: 'source-1', evidence_id: 'evidence-1' },
    { title: '不正な出典', url: 'javascript:alert(1)' },
    { title: '認証情報付きの出典', url: 'https://user:secret@example.com/private' },
    { title: '署名付きURL', url: 'https://example.com/private?X-Amz-Signature=secret' },
    { title: '共有鍵付きURL', url: 'https://example.com/share?rlkey=secret' },
    { title: '', url: 'https://example.com/no-title' },
  ];
  const client = { getHome: vi.fn(async () => ({
    status: 'ready', assets: [], profile: null,
    ideas: [{ id: 'idea-1', title: '出典付きの案', brief_sections: Array(8).fill('章の概要'), brief_citations: citations }],
  })) };
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  mounted = { root, container };
  await act(async () => root.render(<LocalHomeSurface client={client} />));

  const links = [...container.querySelectorAll('.local-home__citation a')];
  expect(links).toHaveLength(1);
  expect(links[0].textContent).toContain('公開統計');
  expect(links[0].getAttribute('href')).toBe('https://example.com/statistics?id=1#section');
  expect(links[0].getAttribute('target')).toBe('_blank');
  expect(links[0].getAttribute('rel')).toContain('noopener');
  expect(container.textContent).not.toContain('署名付きURL');
  expect(container.textContent).not.toContain('共有鍵付きURL');
  const sectionHeadings = [...container.querySelectorAll('.local-home__section-list h3')];
  const citedSection = sectionHeadings.find((heading) => heading.textContent === 'ビジネスモデル');
  expect(citedSection.parentElement.querySelector('.local-home__citation')).not.toBeNull();
  expect(sectionHeadings.find((heading) => heading.textContent === 'エグゼクティブサマリー').parentElement.querySelector('.local-home__citation')).toBeNull();
});

it('does not invent or render citations when a chapter has none', async () => {
  const client = { getHome: vi.fn(async () => ({
    status: 'ready', assets: [], profile: null,
    ideas: [{ id: 'idea-1', title: '出典なしの案', brief_sections: Array(8).fill('保存された概要'), brief_citations: Array.from({ length: 8 }, () => []) }],
  })) };
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  mounted = { root, container };
  await act(async () => root.render(<LocalHomeSurface client={client} />));
  expect(container.querySelectorAll('.local-home__citation')).toHaveLength(0);
  expect(container.querySelectorAll('.local-home__section-list a')).toHaveLength(0);
});
