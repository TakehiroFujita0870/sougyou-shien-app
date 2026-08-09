import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { nextProjectAssistantReply, ProjectSurface } from './ProjectSurface';

describe('ProjectSurface conversation contract', () => {
  it.each(['empty', 'populated', 'loading', 'error'])('renders %s with one composer and five scannable sections', (state) => {
    const html = renderToStaticMarkup(<ProjectSurface state={state} conversationRepository={{ load: async () => [], save: async (messages) => messages }} />);
    expect(html).toContain('project-composer');
    expect(html.match(/data-project-question="true"/g)).toHaveLength(5);
    expect(html).toContain('DOCXをダウンロード');
    expect(html).not.toContain('資料を追加');
    expect(html).not.toContain('AIで補完');
    expect(html).toContain('根拠');
    expect(html).toContain('未確認');
  });

  it('derives a deterministic assistant reply that carries the active project context', () => {
    expect(nextProjectAssistantReply('保全ノート', '現場の記録を探せない')).toContain('保全ノート');
    expect(nextProjectAssistantReply('保全ノート', '現場の記録を探せない')).toContain('現場の記録を探せない');
  });
});
