// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { LocalGraphSurface, semanticGraphData } from './LocalGraphSurface';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const graphImport = vi.hoisted(() => {
  let resolveImport;
  return {
    ready: new Promise((resolve) => { resolveImport = resolve; }),
    release: () => resolveImport(),
  };
});

class MockGraph {
  constructor() {
    this.pauseAnimation = vi.fn();
    this.rendererHandle = { dispose: vi.fn() };
    this._destructor = vi.fn(() => {
      this.pauseAnimation();
      this.rendererHandle.dispose();
    });
  }
  width() { return this; }
  height() { return this; }
  backgroundColor() { return this; }
  showNavInfo() { return this; }
  numDimensions() { return this; }
  graphData(value) { this.data = value; return this; }
  nodeId() { return this; }
  nodeLabel() { return this; }
  nodeColor() { return this; }
  nodeVal() { return this; }
  nodeRelSize() { return this; }
  nodeOpacity() { return this; }
  nodeThreeObject() { return this; }
  nodeThreeObjectExtend() { return this; }
  nodeVisibility() { return this; }
  linkLabel() { return this; }
  linkColor() { return this; }
  linkOpacity() { return this; }
  linkWidth() { return this; }
  linkDirectionalArrowLength() { return this; }
  linkVisibility() { return this; }
  enableNodeDrag() { return this; }
  d3VelocityDecay() { return this; }
  warmupTicks() { return this; }
  cooldownTicks() { return this; }
  onNodeClick(handler) { this.nodeClick = handler; return this; }
  onLinkClick(handler) { this.linkClick = handler; return this; }
  onBackgroundClick() { return this; }
  d3Force() { return { strength() {}, distance() {} }; }
  cameraPosition() { return this; }
  renderer() { return this.rendererHandle; }
}

const mockGraphs = [];
vi.mock('3d-force-graph', async () => {
  await graphImport.ready;
  return { default: class { constructor() {
  const graph = new MockGraph();
  mockGraphs.push(graph);
  return graph;
} } };
});
vi.mock('three-spritetext', () => ({ default: class {} }));

let mounted = [];
afterEach(() => {
  for (const item of mounted) act(() => { item.root.unmount(); item.container.remove(); });
  mounted = [];
  mockGraphs.length = 0;
  vi.restoreAllMocks();
});

async function flushEffects() {
  for (let index = 0; index < 8; index += 1) {
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
  }
}

describe('LocalGraphSurface Facet exploration', () => {
  it('does not construct a graph when navigation cancels its pending imports', async () => {
    const client = {
      getGraph: vi.fn().mockResolvedValue({
        status: 'ready', truncated: false,
        nodes: [{ id: 'idea-1', kind: 'idea', label: '事業案' }], edges: [],
      }),
      getFacetRegion: vi.fn(),
    };
    const container = document.createElement('div');
    document.body.append(container);
    const root = createRoot(container);
    mounted.push({ root, container });
    await act(async () => root.render(<LocalGraphSurface client={client} onOpenServices={() => {}} />));
    await flushEffects();
    expect(container.querySelector('.local-graph__canvas')).toBeTruthy();

    act(() => root.unmount());
    graphImport.release();
    await flushEffects();

    expect(mockGraphs).toHaveLength(0);
  });

  it('keeps the 3D canvas and follows the actual parent-child-record path as wheel depth changes', async () => {
    globalThis.ResizeObserver = class { observe() {} disconnect() {} };
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
    const hit = {
      id: 'idea-child', kind: 'idea', title: '具体の創業案', root_facet_id: 'facet-root',
      matched_facet_id: 'facet-child', depth: 2, classification_status: 'inferred',
      classification_evidence_ids: ['ev-class'], taxonomy_status_path: ['confirmed', 'inferred'],
      taxonomy_evidence_path: [['ev-tax-parent'], ['ev-tax-child']], evidence_ids: ['ev-tax-parent', 'ev-tax-child', 'ev-class'],
      facet_path: [
        { facet_id: 'facet-root', label: '事業領域', depth: 0 },
        { facet_id: 'facet-middle', label: '食品関連', depth: 1 },
        { facet_id: 'facet-child', label: '小規模な食品店', depth: 2 },
      ],
    };
    const directMembership = {
      ...hit, matched_facet_id: 'facet-root', depth: 0, classification_status: 'confirmed',
      classification_evidence_ids: ['ev-class-direct'], taxonomy_status_path: [], taxonomy_evidence_path: [],
      evidence_ids: ['ev-class-direct'],
      facet_path: [{ facet_id: 'facet-root', label: '事業領域', depth: 0 }],
    };
    const client = {
      getGraph: vi.fn().mockResolvedValue({
        status: 'ready', truncated: false,
        nodes: [
          { id: 'facet-root', kind: 'facet', label: '事業領域' },
          { id: 'facet-middle', kind: 'facet', label: '食品関連' },
          { id: 'facet-child', kind: 'facet', label: '小規模な食品店' },
          { id: 'idea-child', kind: 'idea', label: '具体の創業案' },
        ], edges: [],
      }),
      getFacetRegion: vi.fn(async (_facetId, depth) => ({
        status: depth < 2 ? 'empty' : 'ready', facet_id: 'facet-root', depth, hits: depth < 2 ? [] : [hit, directMembership],
      })),
    };
    const container = document.createElement('div');
    document.body.append(container);
    const root = createRoot(container);
    mounted.push({ root, container });
    await act(async () => root.render(<LocalGraphSurface client={client} onOpenServices={() => {}} />));
    await flushEffects();

    expect(container.querySelector('.local-graph__canvas')).toBeTruthy();
    expect(container.querySelector('[role="tablist"]')).toBeNull();
    expect(client.getFacetRegion).not.toHaveBeenCalled();
    await act(async () => {
      const select = container.querySelector('select');
      select.value = 'facet-root';
      select.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await flushEffects();
    expect(client.getFacetRegion).toHaveBeenCalledWith('facet-root', 0, expect.any(Object));
    await act(async () => container.querySelector('.local-graph__canvas').dispatchEvent(new WheelEvent('wheel', { deltaY: 80, bubbles: true, cancelable: true })));
    await flushEffects();
    expect(client.getFacetRegion).toHaveBeenCalledWith('facet-root', 1, expect.any(Object));
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 270)); });
    await act(async () => container.querySelector('.local-graph__canvas').dispatchEvent(new WheelEvent('wheel', { deltaY: 80, bubbles: true, cancelable: true })));
    await flushEffects();
    expect(client.getFacetRegion).toHaveBeenCalledWith('facet-root', 2, expect.any(Object));
    expect(container.textContent).toContain('確定');
    expect(container.textContent).toContain('推測');
    expect(container.textContent).toContain('小規模な食品店');
    expect(container.querySelectorAll('aside[aria-label="分類領域の記録と根拠"] article')).toHaveLength(2);
    expect(container.textContent).not.toContain('Facet');
    expect(container.textContent).toContain('ev-class');
    const graphInstance = mockGraphs.at(-1);
    expect(graphInstance.data.nodes.map(({ id, depth }) => [id, depth])).toEqual([
      ['facet-root', 0], ['facet-middle', 1], ['facet-child', 2], ['idea-child', 2],
    ]);
    expect(graphInstance.data.links.map(({ source, target }) => [source, target])).toEqual([
      ['facet-root', 'facet-middle'], ['facet-middle', 'facet-child'], ['facet-child', 'idea-child'],
      ['facet-root', 'idea-child'],
    ]);
    expect(consoleError.mock.calls.flat().join(' ')).not.toMatch(/same key|unique key/i);
    const canvas = container.querySelector('.local-graph__canvas');
    const removeListener = vi.spyOn(canvas, 'removeEventListener');
    act(() => root.unmount());
    expect(graphInstance._destructor).toHaveBeenCalledOnce();
    expect(graphInstance.pauseAnimation).toHaveBeenCalledOnce();
    expect(graphInstance.rendererHandle.dispose).toHaveBeenCalledOnce();
    expect(removeListener).toHaveBeenCalledWith('wheel', expect.any(Function), true);
    expect(canvas.childElementCount).toBe(0);
    consoleError.mockRestore();
  });

  it('keeps the existing 3D graph and exposes no Facet controls when no Facets exist', async () => {
    globalThis.ResizeObserver = class { observe() {} disconnect() {} };
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const client = {
      getGraph: vi.fn().mockResolvedValue({
        status: 'ready', truncated: false,
        nodes: [{ id: 'idea-1', kind: 'idea', label: '事業案' }, { id: 'asset-1', kind: 'asset', label: '資料' }],
        edges: [{ source: 'idea-1', target: 'asset-1', label: 'USES' }],
      }),
      getFacetRegion: vi.fn(),
    };
    const container = document.createElement('div');
    document.body.append(container);
    const root = createRoot(container);
    mounted.push({ root, container });
    await act(async () => root.render(<LocalGraphSurface client={client} onOpenServices={() => {}} />));
    await flushEffects();
    expect(container.querySelector('.local-graph__canvas')?.getAttribute('aria-label')).toContain('2個の点と1本のつながり');
    expect(container.querySelector('select')).toBeNull();
    expect(client.getFacetRegion).not.toHaveBeenCalled();
  });

  it('renders semantic assertions without scaffold nodes and shows safe provenance when an edge is selected', async () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1280 });
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 720 });
    globalThis.ResizeObserver = class { observe() {} disconnect() {} };
    vi.spyOn(console, 'error').mockImplementation(() => {});
    let resolveProvenance;
    const client = {
      getGraph: vi.fn().mockResolvedValue({
        status: 'ready', truncated: false,
        nodes: [
          { id: 'idea-1', kind: 'idea', label: '店舗の小規模実験' },
          { id: 'asset-1', kind: 'asset', label: '顧客ヒアリング記録' },
          { id: 'assertion-1', kind: 'relation_assertion', label: 'assertion-1' },
          { id: 'revision-1', kind: 'source_revision', label: 'revision-1' },
          { id: 'chunk-1', kind: 'content_chunk', label: 'chunk-1' },
          { id: 'event-1', kind: 'audit_event', label: 'event-1' },
        ],
        edges: [
          { source: 'assertion-1', target: 'idea-1', label: 'ASSERTS_FROM' },
          { source: 'assertion-1', target: 'asset-1', label: 'ASSERTS_TO' },
          { source: 'revision-1', target: 'chunk-1', label: 'HAS_CHUNK' },
        ],
        semantic_edges: [{
          id: 'meaning-1', source_id: 'idea-1', target_id: 'asset-1', predicate: 'USES',
          status: 'inferred', confidence: 0.82, evidence_ids: ['evidence-shareable-1'],
          based_on_brief_id: 'brief-12', based_on_brief_section_index: 2,
        }, {
          id: 'dangling-meaning', source_id: 'missing-node', target_id: 'asset-1', predicate: 'USES',
          status: 'confirmed', confidence: 1, evidence_ids: ['private-evidence'],
        }, {
          id: 'meaning-confirmed', source_id: 'asset-1', target_id: 'idea-1', predicate: 'SUPPORTS',
          status: 'confirmed', confidence: 1, evidence_ids: ['evidence-shareable-2'],
        }],
      }),
      getFacetRegion: vi.fn(),
      getSemanticEdgeProvenance: vi.fn(() => new Promise((resolve) => { resolveProvenance = resolve; })),
    };
    const container = document.createElement('div');
    document.body.append(container);
    const root = createRoot(container);
    mounted.push({ root, container });
    await act(async () => root.render(<LocalGraphSurface client={client} onOpenServices={() => {}} />));
    await flushEffects();

    const projection = semanticGraphData(await client.getGraph());
    expect(projection.nodes.map((node) => node.id)).toEqual(['idea-1', 'asset-1']);
    expect(projection.edges).toEqual([
      expect.objectContaining({ source: 'idea-1', target: 'asset-1', label: 'USES', assertionId: 'meaning-1' }),
      expect.objectContaining({ source: 'asset-1', target: 'idea-1', label: 'SUPPORTS', assertionId: 'meaning-confirmed' }),
    ]);
    expect(semanticGraphData({ ...(await client.getGraph()), semantic_edges: undefined }).edges).toEqual([]);
    expect(container.textContent).not.toContain('assertion-1');
    expect(container.textContent).not.toContain('revision-1');
    expect(container.textContent).not.toContain('chunk-1');
    expect(container.textContent).not.toContain('event-1');
    expect(container.textContent).not.toContain('private-evidence');

    const relationButtons = container.querySelectorAll('[aria-label="意味関係"] button');
    act(() => relationButtons[0].click());
    expect(container.textContent).toContain('推測');
    expect(container.textContent).toContain('82%');
    expect(container.textContent).toContain('evidence-shareable-1');
    expect(container.textContent).toContain('brief-12');
    expect(container.textContent).toContain('観点 2');
    act(() => relationButtons[1].click());
    expect(container.textContent).toContain('確定');
    expect(container.textContent).toContain('100%');

    act(() => relationButtons[0].click());
    act(() => container.querySelector('[aria-label="意味関係と根拠"] button').click());
    await flushEffects();
    expect(client.getSemanticEdgeProvenance).toHaveBeenCalledWith('meaning-1', expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(container.textContent).toContain('根拠を確認中');
    await act(async () => resolveProvenance({
      status: 'ready', assertion_id: 'meaning-1',
      section: { brief_id: 'brief-12', revision: 3, idea_id: 'idea-1', section_index: 2, title: '顧客課題', content: '合成概要の確認用本文。', raw_payload: 'PRIVATE' },
      evidence: [{ id: 'evidence-shareable-1', polarity: 'supports', confidence: 0.82, status: 'active', excerpt: 'PRIVATE' }],
    }));
    expect(container.textContent).toContain('合成概要の確認用本文。');
    expect(container.textContent).toContain('観点 2: 顧客課題');
    expect(container.textContent).not.toContain('観点 3');
    expect(container.textContent).toContain('supports');
    expect(container.textContent).toContain('active');
    expect(container.textContent).not.toContain('PRIVATE');
  });

  it('aborts prior provenance reads and never replaces a newer selection with a stale response', async () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1280 });
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 720 });
    globalThis.ResizeObserver = class { observe() {} disconnect() {} };
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const pending = {};
    const client = {
      getGraph: vi.fn().mockResolvedValue({
        status: 'ready', truncated: false,
        nodes: [{ id: 'idea-1', kind: 'idea', label: '事業案' }, { id: 'asset-1', kind: 'asset', label: '経験' }],
        edges: [],
        semantic_edges: [
          { id: 'edge-one', source_id: 'idea-1', target_id: 'asset-1', predicate: 'USES', status: 'inferred', confidence: 0.7, evidence_ids: ['evidence-1'], based_on_brief_id: 'brief-1', based_on_brief_section_index: 0 },
          { id: 'edge-two', source_id: 'asset-1', target_id: 'idea-1', predicate: 'SUPPORTS', status: 'confirmed', confidence: 1, evidence_ids: ['evidence-2'], based_on_brief_id: 'brief-2', based_on_brief_section_index: 1 },
        ],
      }),
      getFacetRegion: vi.fn(),
      getSemanticEdgeProvenance: vi.fn((id, { signal }) => new Promise((resolve) => { pending[id] = { resolve, signal }; })),
    };
    const container = document.createElement('div');
    document.body.append(container);
    const root = createRoot(container);
    mounted.push({ root, container });
    await act(async () => root.render(<LocalGraphSurface client={client} onOpenServices={() => {}} />));
    await flushEffects();
    const relationButtons = container.querySelectorAll('[aria-label="意味関係"] button');
    act(() => relationButtons[0].click());
    await flushEffects();
    act(() => container.querySelector('[aria-label="意味関係と根拠"] button').click());
    await flushEffects();
    expect(pending['edge-one']).toBeTruthy();

    act(() => relationButtons[1].click());
    await flushEffects();
    expect(pending['edge-one'].signal.aborted).toBe(true);
    expect(container.textContent).not.toContain('古い章の内容');
    act(() => container.querySelector('[aria-label="意味関係と根拠"] button').click());
    await flushEffects();

    await act(async () => pending['edge-one'].resolve({
      status: 'ready', assertion_id: 'edge-one',
      section: { brief_id: 'brief-1', revision: 1, idea_id: 'idea-1', section_index: 0, title: '古い章', content: '古い章の内容' },
      evidence: [{ id: 'evidence-1', polarity: 'supports', confidence: 0.7, status: 'active' }],
    }));
    await flushEffects();
    expect(container.textContent).not.toContain('古い章の内容');
    await act(async () => pending['edge-two'].resolve({
      status: 'ready', assertion_id: 'edge-two',
      section: { brief_id: 'brief-2', revision: 2, idea_id: 'idea-1', section_index: 1, title: '新しい章', content: '新しい章の内容' },
      evidence: [{ id: 'evidence-2', polarity: 'contradicts', confidence: 0.91, status: 'active' }],
    }));
    await flushEffects();
    expect(container.textContent).toContain('新しい章の内容');
    expect(container.textContent).not.toContain('古い章の内容');
  });
});
