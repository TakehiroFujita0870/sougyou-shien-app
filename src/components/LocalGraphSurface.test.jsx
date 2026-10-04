// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { LocalGraphSurface, semanticGraphData } from './LocalGraphSurface';
import { COLORS, starRadius } from './localGraphPresentation.js';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const graphHarness = vi.hoisted(() => {
  let resolveImport;
  let zoomLevel = 0.2;
  return {
    ready: new Promise((resolve) => { resolveImport = resolve; }),
    release: () => resolveImport(),
    props: null,
    dataBeforeForces: false,
    graph: {
      zoomToFit: vi.fn(),
      centerAt: vi.fn(),
      screen2GraphCoords: (x, y) => ({ x, y }),
      zoom: vi.fn((scale) => {
        if (scale === undefined) return zoomLevel;
        zoomLevel = scale;
        return zoomLevel;
      }),
      d3Force: vi.fn(() => {
        const force = { strength: vi.fn(() => force), distance: vi.fn(() => force), distanceMax: vi.fn(() => force) };
        return force;
      }),
      d3ReheatSimulation: vi.fn(),
    },
    resetZoom: () => { zoomLevel = 0.2; },
    instances: [],
    unmounts: [],
  };
});

vi.mock('react-force-graph-2d', async () => {
  await graphHarness.ready;
  const React = await import('react');
  const MockForceGraph2D = React.forwardRef((props, ref) => {
    if (props.graphData.nodes.length && !graphHarness.graph.d3Force.mock.calls.length && !graphHarness.props?.graphData.nodes.length) {
      graphHarness.dataBeforeForces = true;
    }
    graphHarness.props = props;
    React.useImperativeHandle(ref, () => graphHarness.graph, []);
    React.useEffect(() => {
      const instance = { destroyed: false };
      graphHarness.instances.push(instance);
      return () => {
        instance.destroyed = true;
        graphHarness.unmounts.push(instance);
      };
    }, []);
    return React.createElement('div', { className: 'mock-force-graph', 'data-node-count': props.graphData.nodes.length });
  });
  return { default: MockForceGraph2D };
});

let mounted = [];
afterEach(() => {
  for (const item of mounted) act(() => { item.root.unmount(); item.container.remove(); });
  mounted = [];
  graphHarness.props = null;
  graphHarness.dataBeforeForces = false;
  graphHarness.graph.zoomToFit.mockClear();
  graphHarness.graph.centerAt.mockClear();
  graphHarness.graph.zoom.mockClear();
  graphHarness.graph.d3Force.mockClear();
  graphHarness.graph.d3ReheatSimulation.mockClear();
  graphHarness.instances.length = 0;
  graphHarness.unmounts.length = 0;
  graphHarness.resetZoom();
  vi.restoreAllMocks();
});

function pointerEvent(type, x, y) {
  const event = new Event(type, { bubbles: true });
  Object.defineProperties(event, {
    clientX: { value: x },
    clientY: { value: y },
    pointerId: { value: 1 },
    button: { value: 0 },
  });
  return event;
}

async function flushEffects() {
  for (let index = 0; index < 8; index += 1) {
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
  }
}

async function mountGraphSurface(client) {
  const container = document.createElement('div');
  document.body.append(container);
  const root = createRoot(container);
  mounted.push({ root, container });
  await act(async () => root.render(<LocalGraphSurface client={client} onOpenServices={() => {}} />));
  await flushEffects();
  return container;
}

function settleGraph() {
  graphHarness.props.graphData.nodes.forEach((node, index) => {
    if (!Number.isFinite(node.x)) Object.assign(node, { x: index * 60, y: index % 3 * 60 });
  });
  act(() => graphHarness.props.onEngineStop());
}

function clickNode(container, node, movement = 0) {
  settleGraph();
  const current = graphHarness.props.graphData.nodes.find(item => item.id === node.id);
  const canvas = container.querySelector('.local-graph__canvas');
  act(() => {
    canvas.dispatchEvent(pointerEvent('pointerdown', current.x, current.y));
    canvas.dispatchEvent(pointerEvent('pointermove', current.x + movement, current.y));
    canvas.dispatchEvent(pointerEvent('pointerup', current.x + movement, current.y));
  });
}

function clickRelation(container, edge) {
  clickNode(container, { id: typeof edge.source === 'object' ? edge.source.id : edge.source });
  const button = [...container.querySelectorAll('.local-graph__selected-relations button')]
    .find(item => item.textContent.includes(` → ${edge.label} → `));
  act(() => button.click());
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
    graphHarness.release();
    await flushEffects();

    expect(graphHarness.instances).toHaveLength(0);
  });

  it('renders 500 nodes without permanent widgets, supports star selection, and tears down on navigation', async () => {
    const resizeObservers = [];
    globalThis.ResizeObserver = class {
      constructor(callback) { this.callback = callback; this.disconnect = vi.fn(); resizeObservers.push(this); }
      observe() {}
    };
    const nodes = Array.from({ length: 500 }, (_, index) => ({
      id: `node-${index}`,
      kind: index < 3 ? 'facet' : index % 7 === 0 ? 'asset' : 'idea',
      label: index === 419 ? '食品店の顧客調査' : `記録 ${index}`,
    }));
    const edges = Array.from({ length: 1200 }, (_, index) => ({
      source: `node-${index % 500}`,
      target: `node-${(index * 17 + 23) % 500}`,
      label: 'USES',
    })).filter((edge) => edge.source !== edge.target);
    const client = {
      getGraph: vi.fn().mockResolvedValue({
        status: 'ready', truncated: false, nodes, edges,
        semantic_edges: [
          { id: 'tax-root-middle', source_id: 'node-0', target_id: 'node-1', predicate: 'CLASSIFIED_AS', status: 'confirmed', evidence_ids: ['ev-root-middle'] },
          { id: 'tax-middle-leaf', source_id: 'node-1', target_id: 'node-2', predicate: 'CLASSIFIED_AS', status: 'confirmed', evidence_ids: ['ev-middle-leaf'] },
          { id: 'tax-inferred', source_id: 'node-2', target_id: 'node-8', predicate: 'CLASSIFIED_AS', status: 'inferred', evidence_ids: ['ev-inferred'] },
          { id: 'idea-classification', source_id: 'node-9', target_id: 'node-2', predicate: 'CLASSIFIED_AS', status: 'confirmed', evidence_ids: ['ev-classification'] },
        ],
      }),
      getFacetRegion: vi.fn(async (_facetId, searchDepth) => ({ status: 'empty', facet_id: 'node-0', depth: searchDepth, hits: [] })),
    };
    const container = document.createElement('div');
    document.body.append(container);
    const root = createRoot(container);
    mounted.push({ root, container });
    await act(async () => root.render(<LocalGraphSurface client={client} onOpenServices={() => {}} />));
    await flushEffects();

    expect(container.querySelector('.local-graph__canvas')?.getAttribute('aria-label')).toContain('平面の知識グラフ。500個の点と1204本のつながり');
    expect(container.querySelector('.mock-force-graph')?.getAttribute('data-node-count')).toBe('500');
    expect(graphHarness.props.graphData.links).toHaveLength(1204);
    expect(graphHarness.props.enableNodeDrag).toBe(true);
    expect(graphHarness.props.enableZoomInteraction).toBe(true);
    expect(graphHarness.props.enablePanInteraction).toBe(true);
    expect(graphHarness.props.autoPauseRedraw).toBe(true);
    const originalNodeRenderer = graphHarness.props.nodeCanvasObject;
    act(() => graphHarness.props.onNodeHover(nodes[5]));
    expect(graphHarness.props.nodeCanvasObject).not.toBe(originalNodeRenderer);
    expect(typeof graphHarness.props.onEngineStop).toBe('function');
    expect(graphHarness.graph.zoomToFit).not.toHaveBeenCalled();
    expect(graphHarness.graph.d3ReheatSimulation).not.toHaveBeenCalled();
    expect(graphHarness.props.graphData.nodes.slice(0, 3).map(({ abstractionDepth }) => abstractionDepth)).toEqual([0, 1, 2]);
    expect(graphHarness.props.graphData.nodes[8].abstractionDepth).toBeNull();
    expect(container.textContent).not.toContain('深度');
    expect(container.querySelector('.local-graph__depth')).toBeNull();
    expect(client.getFacetRegion).not.toHaveBeenCalled();
    expect(container.querySelector('input[type="search"]')).toBeNull();
    expect(container.querySelector('[aria-label="意味関係"]')).toBeNull();
    clickNode(container, graphHarness.props.graphData.nodes[419], 2);
    expect(container.querySelector('.local-graph__selected')?.textContent).toContain('食品店の顧客調査');
    const incidentLink = graphHarness.props.graphData.links.find((link) => link.source === 'node-419' || link.target === 'node-419');
    const unrelatedLink = graphHarness.props.graphData.links.find((link) => link.source === 'node-0' && link.target === 'node-23');
    expect(graphHarness.props.linkColor(incidentLink)).toContain('0.94');
    expect(graphHarness.props.linkColor(unrelatedLink)).toContain('0.025');
    expect(client.getFacetRegion).not.toHaveBeenCalled();
    const graphInstance = graphHarness.instances.at(-1);
    const resizeObserver = resizeObservers.at(-1);
    act(() => root.unmount());
    expect(graphInstance.destroyed).toBe(true);
    expect(graphHarness.unmounts).toContain(graphInstance);
    expect(resizeObserver.disconnect).toHaveBeenCalledOnce();
  });

  it('initializes compact forces before data and never resets the camera on selection', async () => {
    const client = {
      getGraph: vi.fn().mockResolvedValue({
        status: 'ready', truncated: false, nodes: [{ id: 'idea-1', kind: 'idea', label: '事業案' }], edges: [],
      }),
      getFacetRegion: vi.fn(),
    };
    const container = document.createElement('div');
    document.body.append(container);
    const root = createRoot(container);
    mounted.push({ root, container });
    await act(async () => root.render(<LocalGraphSurface client={client} onOpenServices={() => {}} />));
    await flushEffects();

    expect(graphHarness.graph.d3Force.mock.results[0].value.strength).toHaveBeenCalledWith(-18);
    expect(graphHarness.dataBeforeForces).toBe(false);
    expect(graphHarness.graph.d3Force.mock.results[0].value.distanceMax).toHaveBeenCalledWith(160);
    expect(graphHarness.graph.d3Force.mock.results[1].value.distance).toHaveBeenCalledWith(30);
    expect(graphHarness.graph.zoom).toHaveBeenCalledExactlyOnceWith(0.9, 0);
    const originalData = graphHarness.props.graphData;
    // ForceGraph treats a string mode as a node property, not a constant.
    expect(typeof graphHarness.props.nodeCanvasObjectMode).toBe('function');
    expect(graphHarness.props.nodeCanvasObjectMode(originalData.nodes[0])).toBe('replace');
    const drawContext = {
      save: vi.fn(), restore: vi.fn(), beginPath: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(),
      closePath: vi.fn(), fill: vi.fn(), arc: vi.fn(), stroke: vi.fn(),
      measureText: vi.fn((label) => ({ width: Array.from(label).length * 8 })),
      createRadialGradient: vi.fn(() => ({ addColorStop: vi.fn() })),
      fillText: vi.fn(),
    };
    const fillStyles = [];
    const shadowBlurs = [];
    Object.defineProperty(drawContext, 'fillStyle', { set: (value) => fillStyles.push(value) });
    Object.defineProperty(drawContext, 'shadowBlur', { set: (value) => shadowBlurs.push(value) });
    act(() => graphHarness.props.nodeCanvasObject({ ...originalData.nodes[0], x: undefined, y: NaN }, drawContext, 0.9));
    expect(drawContext.createRadialGradient).not.toHaveBeenCalled();
    expect(drawContext.save).not.toHaveBeenCalled();
    originalData.nodes[0].x = 100;
    originalData.nodes[0].y = 120;
    act(() => {
      graphHarness.props.onRenderFramePre(drawContext, 0.9);
      graphHarness.props.nodeCanvasObject(originalData.nodes[0], drawContext, 0.9);
    });
    expect(drawContext.fillText).toHaveBeenCalledOnce();
    expect(drawContext.fillText.mock.calls[0][0]).toBe('事業案');
    expect(drawContext.fillText.mock.calls[0][1]).toBeCloseTo(100 + starRadius(originalData.nodes[0]) + 9 / 0.9);
    expect(fillStyles).toContain(COLORS.idea);
    expect(shadowBlurs.some((blur) => blur > 0)).toBe(true);
    expect(drawContext.createRadialGradient).toHaveBeenCalledOnce();
    expect(drawContext.lineTo).not.toHaveBeenCalled();
    expect(drawContext.arc).toHaveBeenCalledWith(100, 120, 1.98, 0, Math.PI * 2);
    settleGraph();
    graphHarness.graph.zoom.mockClear();
    graphHarness.graph.d3Force.mockClear();
    const canvas = container.querySelector('.local-graph__canvas');
    act(() => {
      canvas.dispatchEvent(pointerEvent('pointerdown', 20, 20));
      canvas.dispatchEvent(pointerEvent('pointerup', 20, 20));
      canvas.dispatchEvent(pointerEvent('pointerdown', 20, 20));
      canvas.dispatchEvent(pointerEvent('pointermove', 22, 20));
      canvas.dispatchEvent(pointerEvent('pointerup', 20, 20));
    });
    clickNode(container, originalData.nodes[0]);
    expect(graphHarness.props.graphData).toBe(originalData);
    expect(graphHarness.graph.zoomToFit).not.toHaveBeenCalled();
    expect(graphHarness.graph.zoom.mock.calls.every(args => args.length === 0)).toBe(true);
    expect(graphHarness.graph.d3Force).not.toHaveBeenCalled();
  });

  it('fits only the settled initial layout, then preserves user zoom and dragged positions', async () => {
    const client = { getGraph: vi.fn().mockResolvedValue({
      status: 'ready', nodes: [{ id: 'a', kind: 'idea', label: '案' }, { id: 'b', kind: 'asset', label: '経験' }], edges: [],
    }) };
    const container = await mountGraphSurface(client);
    expect(graphHarness.props.cooldownTicks).toBe(0);
    expect(container.querySelector('.mock-force-graph').parentElement.style.visibility).toBe('hidden');
    act(() => graphHarness.props.onEngineStop());
    expect(graphHarness.graph.centerAt).not.toHaveBeenCalled();
    Object.assign(graphHarness.props.graphData.nodes[0], { x: -150, y: -150 });
    Object.assign(graphHarness.props.graphData.nodes[1], { x: 150, y: 150 });
    act(() => graphHarness.props.onEngineStop());
    expect(graphHarness.graph.centerAt).toHaveBeenCalledExactlyOnceWith(0, 0, 0);
    expect(graphHarness.graph.zoom.mock.calls.at(-1)[0]).toBeGreaterThan(0.9);
    expect(container.querySelector('.mock-force-graph').parentElement.style.visibility).toBe('visible');
    graphHarness.graph.zoom(2.5);
    graphHarness.graph.zoom.mockClear();
    graphHarness.graph.centerAt.mockClear();
    graphHarness.props.graphData.nodes[0].x = 99;
    act(() => {
      graphHarness.props.onEngineStop();
    });
    clickNode(container, graphHarness.props.graphData.nodes[0]);
    expect(graphHarness.props.graphData.nodes[0].x).toBe(99);
    expect(graphHarness.graph.zoom.mock.calls.every(args => args.length === 0)).toBe(true);
    expect(graphHarness.graph.centerAt.mock.calls.every(args => args.length === 0)).toBe(true);
  });

  it('keeps the existing graph data and exposes no Facet controls when no Facets exist', async () => {
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

  it('opens safe source URLs in a new tab and preserves selection for other nodes', async () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1280 });
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 720 });
    globalThis.ResizeObserver = class { observe() {} disconnect() {} };
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const open = vi.spyOn(window, 'open').mockImplementation(() => null);
    const nodes = [
      { id: 'source-public', kind: 'source', label: '公開資料', url: 'https://example.test/research' },
      { id: 'source-unsafe', kind: 'source', label: '危険な出典', url: 'javascript:alert(1)' },
      { id: 'source-missing', kind: 'source', label: 'URLなし' },
      { id: 'idea-1', kind: 'idea', label: '事業案' },
    ];
    const client = {
      getGraph: vi.fn().mockResolvedValue({ status: 'ready', truncated: false, nodes, edges: [] }),
      getFacetRegion: vi.fn(),
    };
    const container = document.createElement('div');
    document.body.append(container);
    const root = createRoot(container);
    mounted.push({ root, container });
    await act(async () => root.render(<LocalGraphSurface client={client} onOpenServices={() => {}} />));
    await flushEffects();
    clickNode(container, nodes[0], 5);
    act(() => graphHarness.props.onNodeClick(nodes[0]));
    expect(open).toHaveBeenCalledOnce();
    expect(open).toHaveBeenCalledWith('https://example.test/research', '_blank', 'noopener,noreferrer');
    expect(container.querySelector('.local-graph__canvas')).toBeTruthy();
    expect(container.querySelector('.local-graph__selected')).toBeNull();

    clickNode(container, nodes[1]);
    expect(open).toHaveBeenCalledOnce();
    expect(container.querySelector('.local-graph__selected')?.textContent).toContain('危険な出典');

    clickNode(container, nodes[2]);
    expect(open).toHaveBeenCalledOnce();
    expect(container.querySelector('.local-graph__selected')?.textContent).toContain('URLなし');

    clickNode(container, nodes[3]);
    expect(open).toHaveBeenCalledOnce();
    expect(container.querySelector('.local-graph__selected')?.textContent).toContain('事業案');
  });

  it('selects names with minor jitter, restores native micro-movement, and rejects cancelled or real drags', async () => {
    const container = await mountGraphSurface({ getGraph: vi.fn().mockResolvedValue({
      status: 'ready', nodes: [{ id: 'a', kind: 'idea', label: '事業案' },
        { id: 'b', kind: 'asset', label: '経験' }], edges: [],
    }) });
    settleGraph();
    const node = graphHarness.props.graphData.nodes[0];
    Object.assign(node, { x: 100, y: 100 });
    Object.assign(graphHarness.props.graphData.nodes[1], { x: 400, y: 400 });
    const canvas = container.querySelector('.local-graph__canvas');
    act(() => graphHarness.props.onRenderFramePre({ save() {}, restore() {}, measureText: () => ({ width: 36 }) }, 1));
    act(() => {
      canvas.dispatchEvent(pointerEvent('pointerdown', 130, 100));
      canvas.dispatchEvent(pointerEvent('pointermove', 132, 100));
      canvas.dispatchEvent(pointerEvent('pointerup', 132, 100));
    });
    expect(container.querySelector('.local-graph__selected')?.textContent).toContain('事業案');
    act(() => {
      canvas.dispatchEvent(pointerEvent('pointerdown', 100, 100));
      node.x = 102; // Simulate d3's pre-threshold movement.
      canvas.dispatchEvent(pointerEvent('pointerup', 102, 100));
    });
    expect(node.x).toBe(100);
    clickNode(container, graphHarness.props.graphData.nodes[1], 6);
    expect(container.querySelector('.local-graph__selected')?.textContent).toContain('事業案');
    act(() => {
      canvas.dispatchEvent(pointerEvent('pointerdown', 400, 400));
      canvas.dispatchEvent(pointerEvent('pointermove', 420, 400));
      canvas.dispatchEvent(pointerEvent('pointerup', 400, 400));
      canvas.dispatchEvent(pointerEvent('pointerdown', 400, 400));
      canvas.dispatchEvent(pointerEvent('pointercancel', 400, 400));
      canvas.dispatchEvent(pointerEvent('pointerup', 400, 400));
    });
    expect(container.querySelector('.local-graph__selected')?.textContent).toContain('事業案');
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
      expect.objectContaining({ source: 'idea-1', target: 'asset-1', label: '利用する', assertionId: 'meaning-1' }),
      expect.objectContaining({ source: 'asset-1', target: 'idea-1', label: '支える', assertionId: 'meaning-confirmed' }),
    ]);
    expect(semanticGraphData({ ...(await client.getGraph()), semantic_edges: undefined }).edges).toEqual([]);
    expect(container.textContent).not.toContain('assertion-1');
    expect(container.textContent).not.toContain('revision-1');
    expect(container.textContent).not.toContain('chunk-1');
    expect(container.textContent).not.toContain('event-1');
    expect(container.textContent).not.toContain('private-evidence');

    const graphAssertion = graphHarness.props.graphData.links.find((edge) => edge.assertionId === 'meaning-1');
    clickRelation(container, graphAssertion);
    expect(container.querySelector('[aria-label="意味関係と根拠"]')?.textContent)
      .toContain('店舗の小規模実験 → 利用する → 顧客ヒアリング記録');
    expect(container.querySelector('[aria-label="意味関係と根拠"]')?.textContent).not.toContain('meaning-1');
    expect(container.querySelector('[aria-label="意味関係と根拠"]')?.textContent).not.toContain('evidence-shareable-1');
    const relationButtons = graphHarness.props.graphData.links.map(edge => ({ click: () => clickRelation(container, edge) }));
    relationButtons[0].click();
    expect(container.textContent).toContain('推測');
    expect(container.textContent).toContain('82%');
    expect(container.textContent).toContain('店舗の小規模実験 → 利用する → 顧客ヒアリング記録');
    expect(container.textContent).toContain('根拠 1件');
    expect(container.textContent).toContain('概要の第3観点');
    expect(container.textContent).not.toContain('evidence-shareable-1');
    expect(container.textContent).not.toContain('brief-12');
    relationButtons[1].click();
    expect(container.textContent).toContain('確定');
    expect(container.textContent).toContain('100%');

    relationButtons[0].click();
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
    expect(container.textContent).toContain('第3観点: 顧客課題');
    expect(container.textContent).not.toContain('brief-12');
    expect(container.textContent).not.toContain('evidence-shareable-1');
    expect(container.textContent).toContain('支持');
    expect(container.textContent).toContain('有効');
    expect(container.textContent).not.toContain('PRIVATE');

    clickNode(container, graphHarness.props.graphData.nodes[0]);
    expect(container.querySelector('[aria-label="関連する意味関係"]')?.textContent)
      .toContain('店舗の小規模実験 → 利用する → 顧客ヒアリング記録');
    expect(container.textContent).not.toContain('meaning-1');
    expect(container.textContent).not.toContain('evidence-shareable-1');
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
    const relationButtons = graphHarness.props.graphData.links.map(edge => ({ click: () => clickRelation(container, edge) }));
    relationButtons[0].click();
    await flushEffects();
    act(() => container.querySelector('[aria-label="意味関係と根拠"] button').click());
    await flushEffects();
    expect(pending['edge-one']).toBeTruthy();

    relationButtons[1].click();
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
