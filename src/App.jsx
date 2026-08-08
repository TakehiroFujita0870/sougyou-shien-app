import { useState } from 'react';

import { IdeaForm } from './components/IdeaForm';
import { PipelineProgress } from './components/PipelineProgress';

export function App() {
  const [idea, setIdea] = useState(null);

  return (
    <main className="min-h-screen bg-stone-50 text-emerald-950">
      <header className="border-b border-stone-200 bg-white/90">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-5 sm:px-8">
          <strong className="text-2xl tracking-tight">Kadode</strong>
          <span className="text-sm font-medium text-emerald-800">
            アイデアを、構造で育てる。
          </span>
        </div>
      </header>

      <div className="mx-auto grid max-w-6xl gap-8 px-5 py-10 sm:px-8 lg:grid-cols-[1.15fr_0.85fr] lg:py-16">
        <section aria-labelledby="idea-heading">
          <p className="text-sm font-bold text-emerald-700">最初の一案</p>
          <h1 id="idea-heading" className="mt-3 text-4xl font-bold tracking-tight sm:text-6xl">
            始める前に、
            <br />
            ダメな理由を見つけよう。
          </h1>
          <p className="mt-5 max-w-2xl text-base leading-7 text-stone-700 sm:text-lg">
            誰のどんな痛みを解く案かを記録し、迎合しない反証と一次検証へ進めます。
          </p>

          <div className="mt-8">
            {idea ? (
              <article className="rounded-3xl border border-emerald-200 bg-white p-6 shadow-sm">
                <p className="text-xs font-bold tracking-[0.16em] text-emerald-700">登録済み・STAGE 0</p>
                <h2 className="mt-2 text-2xl font-bold">{idea.title}</h2>
                <p className="mt-3 leading-7 text-stone-700">{idea.ideaSummary}</p>
                <dl className="mt-5 rounded-2xl bg-stone-100 p-4">
                  <dt className="text-xs font-bold text-stone-500">誰の、何のペインか</dt>
                  <dd className="mt-1 leading-6">{idea.painStatement}</dd>
                </dl>
                <p className="mt-4 text-sm text-stone-500">
                  現在はブラウザ内の下書きです。外部サービスには送信していません。
                </p>
                <button
                  type="button"
                  onClick={() => setIdea(null)}
                  className="mt-5 rounded-full border border-emerald-800 px-5 py-2.5 text-sm font-bold text-emerald-900 hover:bg-emerald-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-800"
                >
                  入力し直す
                </button>
              </article>
            ) : (
              <IdeaForm onSubmit={setIdea} />
            )}
          </div>
        </section>

        <aside aria-label="アイデアの進捗">
          <PipelineProgress currentStage={idea ? 0 : null} />
        </aside>
      </div>
    </main>
  );
}
