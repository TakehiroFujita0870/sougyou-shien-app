// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { describe, expect, it } from 'vitest';

import { useHydratedResource } from './useHydratedResource';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

function deferred() {
  let resolve;
  const promise = new Promise((resolvePromise) => { resolve = resolvePromise; });
  return { promise, resolve };
}

describe('useHydratedResource replacement ordering', () => {
  it('does not let a delayed initial load replace a newer adopted project', async () => {
    const pending = deferred();
    const repository = { load: () => pending.promise };
    let resource;
    function Harness() {
      resource = useHydratedResource(repository);
      return <p>{resource.phase}:{resource.value?.title ?? 'none'}</p>;
    }
    const container = document.createElement('div');
    document.body.append(container);
    const root = createRoot(container);
    await act(async () => root.render(<Harness />));

    await act(async () => resource.replaceReady({ id: 'adopted-1', title: '採用後のプロジェクト' }));
    expect(container.textContent).toBe('ready:採用後のプロジェクト');

    await act(async () => pending.resolve(null));
    expect(container.textContent).toBe('ready:採用後のプロジェクト');

    await act(() => { root.unmount(); container.remove(); });
  });
});
