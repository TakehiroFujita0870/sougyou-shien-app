import { useCallback, useEffect, useState } from 'react';
import { FounderGraphReadClientError } from './founderGraphReadClient';
import { FounderGraphSurface } from './FounderGraphSurface';

const INITIAL_STATE = { state: 'loading', results: [] };

/**
 * Loads one explicit Founder Graph query for the existing read-only surface.
 * It deliberately has no default client: the app must opt into a local
 * endpoint and local owner before a browser request can be made.
 */
export function FounderGraphLiveRead({ client, query, initialCategory, reports }) {
  const [view, setView] = useState(INITIAL_STATE);
  const [attempt, setAttempt] = useState(0);

  const retry = useCallback(() => setAttempt((value) => value + 1), []);

  useEffect(() => {
    const searchQuery = typeof query === 'string' ? query.trim() : '';
    if (!searchQuery) {
      setView({ state: 'empty', results: [] });
      return undefined;
    }
    if (!client || typeof client.search !== 'function') {
      setView({ state: 'unavailable', results: [] });
      return undefined;
    }

    const controller = new AbortController();
    setView(INITIAL_STATE);
    Promise.resolve(client.search(searchQuery, { signal: controller.signal }))
      .then((results) => {
        if (controller.signal.aborted) return;
        const safeResults = Array.isArray(results) ? results : [];
        setView({ state: safeResults.length ? 'ready' : 'empty', results: safeResults });
      })
      .catch((error) => {
        if (controller.signal.aborted || error?.name === 'AbortError') return;
        setView({ state: error instanceof FounderGraphReadClientError && error.kind === 'unavailable' ? 'unavailable' : 'error', results: [] });
      });

    return () => controller.abort();
  }, [attempt, client, query]);

  return (
    <FounderGraphSurface
      initialCategory={initialCategory}
      onRetry={view.state === 'unavailable' || view.state === 'error' ? retry : undefined}
      reports={reports}
      results={view.results}
      state={view.state}
    />
  );
}

export default FounderGraphLiveRead;
