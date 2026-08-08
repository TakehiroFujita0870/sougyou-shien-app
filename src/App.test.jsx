/** @vitest-environment jsdom */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { App } from './App';

describe('MVP workspace shell', () => {
  it('prioritizes the first profile interview and exposes every workspace', () => {
    render(<App />);

    expect(screen.getByRole('dialog', { name: 'あなたの情報' })).toBeTruthy();
    expect(screen.getByText('local / fake モード')).toBeTruthy();
    ['アイデア', '横断調査', '資料', '設定', 'AI広報'].forEach((label) => {
      expect(screen.getByRole('button', { name: label })).toBeTruthy();
    });
  });

  it('changes workspaces through keyboard-accessible navigation with a visible focus style', async () => {
    const user = userEvent.setup();
    render(<App />);

    const research = screen.getByRole('button', { name: '横断調査' });
    expect(research.className).toContain('focus-visible:outline');
    research.focus();
    await user.keyboard('{Enter}');

    expect(research.getAttribute('aria-current')).toBe('page');
    expect(screen.getByRole('heading', { name: '反証のために、根拠を集める' })).toBeTruthy();
    expect(screen.getByText('ローカルの fake 結果だけを表示します。外部サービスへ送信しません。')).toBeTruthy();
  });
});
