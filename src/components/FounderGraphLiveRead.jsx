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
  const [searchInput, setSearchInput] = useState(() => typeof query === 'string' ? query : '');
  const [submittedQuery, setSubmittedQuery] = useState(() => typeof query === 'string' ? query : '');

  const retry = useCallback(() => setAttempt((value) => value + 1), []);

  function submitSearch(event) {
    event.preventDefault();
    setSubmittedQuery(searchInput);
    setAttempt((value) => value + 1);
  }

  useEffect(() => {
    const searchQuery = submittedQuery.trim();
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
  }, [attempt, client, submittedQuery]);

  return (
    <div className="grid gap-5">
      <form onSubmit={submitSearch} className="flex flex-wrap items-end gap-3" role="search" aria-label="Founder Graphを検索">
        <label htmlFor="founder-graph-search" className="grid gap-1 text-sm font-medium">
          保存済みの情報を検索
          <input
            id="founder-graph-search"
            type="search"
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            className="min-w-64 rounded-lg border border-[var(--color-border-subtle)] bg-[var(--color-surface)] px-3 py-2 text-base"
          />
        </label>
        <button type="submit" className="rounded-lg border border-[var(--color-border-subtle)] px-4 py-2 font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring)]">検索</button>
      </form>
      <FounderGraphSurface
        initialCategory={initialCategory}
        onRetry={view.state === 'unavailable' || view.state === 'error' ? retry : undefined}
        reports={reports}
        results={view.results}
        state={view.state}
      />
    </div>
  );
}

export default FounderGraphLiveRead;
