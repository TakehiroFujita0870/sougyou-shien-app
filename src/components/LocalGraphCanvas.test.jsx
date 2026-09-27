import { expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { LocalGraphCanvas } from './LocalGraphCanvas.jsx';

it('can compose the graph canvas without opening a renderer or querying provenance during render', () => {
  const client = { getSemanticEdgeProvenance() { throw new Error('render must not read provenance'); } };
  expect(renderToStaticMarkup(<LocalGraphCanvas client={client} nodes={[]} edges={[]} depth={0} onDepthChange={() => {}} />)).toContain('立体の知識グラフ。0個の点と0本のつながり。');
});
