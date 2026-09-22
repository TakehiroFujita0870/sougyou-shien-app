// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { useState } from 'react';
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

  it('supports anchored and inline modes, action slots, model selection, and default empty-send policy', () => {
    const onSubmit = vi.fn(); const onModelChange = vi.fn(); const view = mount({ mode: 'anchored', value: '   ', onSubmit, onModelChange, leadingActions: <button type="button">補完</button> });
    expect(view.container.querySelector('form').className).toContain('Dots-composer--anchored');
    expect(view.container.querySelector('button[type="submit"]').disabled).toBe(true);
    expect(view.container.querySelector('button[aria-label^="モデル:"]').disabled).toBe(false);
    expect(view.container.textContent).toContain('補完'); view.unmount();
  });

  it('enables after typing, preserves Shift+Enter, submits with Enter, and disables after the controlled value clears', () => {
    const onSubmit = vi.fn();
    function Harness() {
      const [value, setValue] = useState('');
      return <AiComposer id="controlled-composer" label="相談" value={value} onValueChange={setValue} onSubmit={(next) => { onSubmit(next); setValue(''); }} models={[{ logicalKey: 'terra', displayName: 'Terra' }]} modelKey="terra" />;
    }
    const container = document.createElement('div'); document.body.append(container); const root = createRoot(container);
    act(() => root.render(<Harness />));
    const textarea = container.querySelector('textarea'); const send = container.querySelector('button[type="submit"]');
    expect(send.disabled).toBe(true);
    const setTextareaValue = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
    act(() => { setTextareaValue.call(textarea, '  相談内容  '); textarea.dispatchEvent(new Event('input', { bubbles: true })); });
    expect(send.disabled).toBe(false);
    act(() => textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', shiftKey: true, bubbles: true, cancelable: true })));
    expect(onSubmit).not.toHaveBeenCalled();
    act(() => textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })));
    expect(onSubmit).toHaveBeenCalledWith('  相談内容  ');
    expect(textarea.value).toBe(''); expect(send.disabled).toBe(true);
    act(() => root.unmount()); container.remove();
  });
});
