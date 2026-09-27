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
  expect(container.textContent).toContain('7. リスクミニマムなロードマップ');
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
  expect(container.textContent).toContain('状態未確認');
  expect(container.textContent).toContain('保存された概要');
  expect(container.textContent).not.toContain('調査済み');
});

it('keeps the research state beside each idea title in a compact, named badge', async () => {
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
    expect(card.querySelector('.local-home__status-badge')).not.toBeNull();
    expect(card.querySelector('.local-home__idea-heading strong + .local-home__status-badge')).not.toBeNull();
  }
  expect(cards.map((card) => card.querySelector('.local-home__status-badge').textContent)).toEqual(['未調査', '調査済み', '過去調査あり']);
  expect(cards.map((card) => card.querySelector('.local-home__status-badge').getAttribute('data-research-state'))).toEqual(['unresearched', 'researched', 'prior_research_import']);
  expect(cards[2].textContent).not.toContain('ResearchRun');
  expect(cards[2].querySelector('.local-home__status-badge').getAttribute('aria-label')).toBe('過去調査を取り込みました（実行済み調査ではありません）');
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
  expect(container.textContent.match(/調査済み・出典を表示できません/g)).toHaveLength(1);
  expect(container.querySelector('.local-home__status-badge').textContent).toBe('調査済み・出典未表示');
  expect(container.querySelector('.local-home__status-badge').getAttribute('data-research-state')).toBe('research_sources_missing');
  expect(container.textContent).not.toContain('未調査');
  expect(container.textContent).not.toContain('調査状態未確認');
  expect(container.textContent).toContain('保存された調査概要');
  expect(container.querySelectorAll('.local-home__citation')).toHaveLength(0);
});

it('labels imported past research distinctly and keeps imported missing citations out of the draft state', async () => {
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
  expect(container.textContent).toContain('過去調査を取り込みました');
  expect([...container.querySelectorAll('.local-home__status-badge')].map((badge) => badge.textContent)).toEqual(['過去調査あり', '過去調査あり']);
  expect(container.querySelectorAll('.local-home__status-badge[data-research-state^="prior_research"]')).toHaveLength(2);
  expect(container.textContent).not.toContain('未調査');
  expect([...container.querySelectorAll('.local-home__citation a')].map((link) => link.textContent)).toContain('公開出典');
});

it('edits title and content through the same form for any asset and supports cancel', async () => {
  const assets = [
    { id: 'asset-1', name: '経験', kind: 'experience', description: '内容1', revision: 1 },
    { id: 'asset-2', name: '資料', kind: 'document', description: '内容2', revision: 1 },
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
  expect(container.querySelectorAll('.local-home__asset-card')).toHaveLength(2);
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
  const citedSection = sectionHeadings.find((heading) => heading.textContent.includes('1. ビジネスモデル'));
  expect(citedSection.parentElement.querySelector('.local-home__citation')).not.toBeNull();
  expect(sectionHeadings.find((heading) => heading.textContent.includes('0. エグゼクティブサマリー')).parentElement.querySelector('.local-home__citation')).toBeNull();
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
