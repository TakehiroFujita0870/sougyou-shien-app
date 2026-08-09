import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { ProjectSurface } from './ProjectSurface';

describe('ProjectSurface presentation contract', () => {
  it.each(['empty', 'populated', 'loading', 'error'])('renders %s with one composer and five scannable sections', (state) => {
    const html = renderToStaticMarkup(<ProjectSurface state={state} />);
    expect(html).toContain('project-composer');
    expect(html.match(/<article/g)).toHaveLength(5);
    expect(html).toContain('Enterで送信、Shift+Enterで改行');
  });
  it('exposes labelled composer and 44px send target', () => {
    const html = renderToStaticMarkup(<ProjectSurface />);
    expect(html).toContain('for="project-composer"');
    expect(html).toContain('min-h-11');
  });
});
