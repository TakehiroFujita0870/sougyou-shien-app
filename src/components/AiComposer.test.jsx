// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { describe, expect, it, vi } from 'vitest';

import { AiComposer } from './AiComposer';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

function mount(props = {}) {
  const container = document.createElement('div'); document.body.append(container); const root = createRoot(container);
  act(() => root.render(<AiComposer id="shared-composer" label="AIへ相談" value="相談内容" onValueChange={() => {}} onSubmit={() => {}} models={[{ logicalKey: 'terra', displayName: 'Terra' }]} modelKey="terra" {...props} />));
  return { container, unmount: () => { act(() => root.unmount()); container.remove(); } };
}

describe('AiComposer', () => {
  it('submits with Enter and preserves Shift+Enter for a newline', () => {
    const onSubmit = vi.fn(); const view = mount({ onSubmit }); const textarea = view.container.querySelector('textarea');
    act(() => textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', shiftKey: true, bubbles: true, cancelable: true })));
    expect(onSubmit).not.toHaveBeenCalled();
    act(() => textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })));
    expect(onSubmit).toHaveBeenCalledWith('相談内容', expect.anything()); view.unmount();
  });

  it('supports anchored and inline modes, action slots, model selection, and empty-send policy', () => {
    const onSubmit = vi.fn(); const onModelChange = vi.fn(); const view = mount({ mode: 'anchored', value: '', disableSendWhenEmpty: true, onSubmit, onModelChange, leadingActions: <button type="button">補完</button> });
    expect(view.container.querySelector('form').className).toContain('kadode-composer--anchored');
    expect(view.container.querySelector('button[type="submit"]').disabled).toBe(true);
    expect(view.container.textContent).toContain('補完'); view.unmount();
  });
});
