import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { ProjectSurface } from './ProjectSurface';

describe('ProjectSurface presentation contract', () => {
  it.each(['empty', 'populated', 'loading', 'error'])('renders %s with one composer and five scannable sections', (state) => {
    const html = renderToStaticMarkup(<ProjectSurface state={state} />);
    expect(html).toContain('project-composer');
    expect(html.match(/<article/g)).toHaveLength(5);
    expect(html).toContain('根拠:');
    expect(html).toContain('未確定:');
  });
  it('keeps the composer labelled and the send target at least 44px tall', () => {
    const html = renderToStaticMarkup(<ProjectSurface />);
    expect(html).toContain('aria-label="Project Kadode AI composer"');
    expect(html).toContain('for="project-composer"');
    expect(html).toContain('min-h-11');
  });
});
