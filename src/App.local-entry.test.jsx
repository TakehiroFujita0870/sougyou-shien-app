import { afterEach, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { App } from './App.jsx';

vi.mock('./components/planSubscriptionRepository', async (importOriginal) => ({
  ...await importOriginal(),
  createLocalPlanRepository: vi.fn(() => { throw new Error('legacy repository must not initialize for Dots dashboard'); }),
}));
afterEach(() => vi.unstubAllGlobals());

it('renders the exact local dashboard without initializing the legacy workspace repositories', () => {
  vi.stubGlobal('location', { protocol: 'http:', hostname: 'localhost', port: '8765', origin: 'http://localhost:8765' });
  expect(renderToStaticMarkup(<App />)).toContain('人的ネットワーク');
});
