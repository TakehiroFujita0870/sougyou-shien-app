import { useCallback, useEffect, useRef, useState } from 'react';

const loading = { phase: 'loading', value: null };

export function useHydratedResource(repository) {
  const [state, setState] = useState(loading);
  const [attempt, setAttempt] = useState(0);
  const requestId = useRef(0);

  useEffect(() => {
    let mounted = true;
    const currentRequest = ++requestId.current;

    Promise.resolve()
      .then(() => repository.load())
      .then((value) => {
        if (mounted && requestId.current === currentRequest) setState({ phase: 'ready', value });
      })
      .catch(() => {
        if (mounted && requestId.current === currentRequest) setState({ phase: 'error', value: null });
      });

    return () => { mounted = false; };
  }, [repository, attempt]);

  const retry = useCallback(() => {
    setState(loading);
    setAttempt((current) => current + 1);
  }, []);

  const replaceReady = useCallback((value) => setState({ phase: 'ready', value }), []);

  return { ...state, retry, replaceReady };
}
