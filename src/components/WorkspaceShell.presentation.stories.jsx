import { expect, within } from 'storybook/test';

const SURFACES = ['Home', 'Project', 'Knowledge'];

const VIEWPORTS = {
  desktop: { name: 'Desktop 1280px', styles: { width: '1280px', height: '800px' }, type: 'desktop' },
  mobile390: { name: 'Mobile 390px', styles: { width: '390px', height: '844px' }, type: 'mobile' },
};

const STATE_COPY = {
  empty: { label: 'Empty', title: '最初の一歩を置く', description: '考えていることを一つ書くと、workspaceの文脈で整理できます。' },
  populated: { label: 'Populated', title: '最近の活動', description: 'いま見ているsurfaceに必要な情報だけを表示します。' },
  loading: { label: 'Loading', title: '読み込んでいます', description: 'surfaceの準備が終わるまで、現在位置を保持します。' },
  error: { label: 'Error', title: '読み込めませんでした', description: '接続状態を確認して、もう一度試してください。' },
};

function ContractPreview({ state = 'empty', activeSurface = 'Home' }) {
  const copy = STATE_COPY[state];
  const isLoading = state === 'loading';
  const isError = state === 'error';

  return (
    <div className="min-h-[520px] overflow-hidden rounded-2xl border border-stone-200 bg-[#f8f5ed] text-stone-900 shadow-sm">
      <header className="flex items-center justify-between gap-4 border-b border-stone-200 bg-[#fffdf8] px-4 py-3">
        <div className="min-w-0 text-sm">
          <span className="text-stone-500">Workspace</span>
          <span aria-hidden="true" className="mx-2 text-stone-400">/</span>
          <strong>{activeSurface}</strong>
        </div>
        <span className="shrink-0 rounded-full border border-stone-300 px-2 py-1 text-xs font-semibold text-stone-600">local / fake</span>
      </header>

      <div className="grid min-h-[472px] md:grid-cols-[176px_minmax(0,1fr)]">
        <nav aria-label="Primary workspace surfaces" className="border-b border-stone-200 bg-[#fffdf8] p-3 md:border-b-0 md:border-r">
          <p className="mb-2 px-2 text-xs font-semibold uppercase tracking-[0.14em] text-stone-500">Surfaces</p>
          <ul className="grid gap-1">
            {SURFACES.map((surface) => (
              <li key={surface}>
                <button type="button" aria-current={activeSurface === surface ? 'page' : undefined} className="min-h-10 w-full rounded-lg px-2 text-left text-sm font-semibold aria-[current=page]:bg-stone-100">
                  {surface}
                </button>
              </li>
            ))}
          </ul>
        </nav>

        <main aria-labelledby="presentation-preview-heading" className="min-w-0 p-4 sm:p-6">
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-stone-500" aria-label="Current context">{activeSurface} context</p>
          <h1 id="presentation-preview-heading" className="mt-2 text-xl font-semibold tracking-tight">{copy.title}</h1>
          <p className="mt-2 max-w-xl text-sm leading-6 text-stone-600">{copy.description}</p>

          <section className="mt-6 rounded-xl border border-stone-200 bg-[#fffdf8] p-4" aria-label={`${copy.label} state`} aria-busy={isLoading}>
            {isError && <p role="alert" className="mb-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm font-semibold text-rose-900">読み込みに失敗しました。再試行できます。</p>}
            {state === 'populated' && <ul className="mb-4 grid gap-2 text-sm text-stone-700"><li>現在の文脈を確認しました</li><li>次に見る資料を整理しました</li></ul>}
            {isLoading && <p role="status" className="mb-4 text-sm text-stone-600">準備しています…</p>}
            <form className="border-t border-stone-100 pt-3"><label htmlFor={`presentation-composer-${state}`} className="sr-only">Dots. AIへのメッセージ</label><textarea id={`presentation-composer-${state}`} aria-describedby={`presentation-composer-hint-${state}`} disabled={isLoading} placeholder="考えていることを入力" className="min-h-20 w-full resize-y rounded-lg border border-stone-200 p-3 text-sm" /><p id={`presentation-composer-hint-${state}`} className="mt-2 text-xs text-stone-500">Enterで送信、Shift+Enterで改行</p><div className="mt-2 flex justify-end"><button type="submit" disabled={isLoading} className="min-h-11 rounded-full bg-stone-900 px-4 text-sm font-semibold text-white disabled:opacity-50">送信</button></div></form>
          </section>
        </main>
      </div>
    </div>
  );
}

export default {
  title: 'Dots./WorkspaceShell Presentation Contract',
  component: ContractPreview,
  parameters: { layout: 'fullscreen', viewport: { viewports: VIEWPORTS } },
};

const assertComposer = async ({ canvasElement }) => {
  const canvas = within(canvasElement);
  const composer = canvas.getByLabelText('Dots. AIへのメッセージ');
  const send = canvas.getByRole('button', { name: '送信' });
  expect(composer).toHaveAttribute('aria-describedby');
  expect(canvas.getByText('Enterで送信、Shift+Enterで改行')).toBeInTheDocument();
  expect(send).toHaveClass('min-h-11');
};

export const Empty = { args: { state: 'empty', activeSurface: 'Home' }, play: assertComposer };
export const Populated = { args: { state: 'populated', activeSurface: 'Project' }, play: assertComposer };
export const Loading = { args: { state: 'loading', activeSurface: 'Knowledge' }, play: assertComposer };
export const Error = { args: { state: 'error', activeSurface: 'Home' }, play: assertComposer };
export const Mobile390 = { args: { state: 'populated', activeSurface: 'Project' }, play: assertComposer, parameters: { viewport: { defaultViewport: 'mobile390' } } };
export const Desktop = { args: { state: 'populated', activeSurface: 'Project' }, play: assertComposer, parameters: { viewport: { defaultViewport: 'desktop' } } };
