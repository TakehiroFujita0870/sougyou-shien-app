import { useState } from 'react';

export const EMPTY_IDEA = {
  title: '',
  ideaSummary: '',
  painStatement: '',
};

export function validateIdea(values) {
  const errors = {};
  const title = values.title.trim();
  const ideaSummary = values.ideaSummary.trim();
  const painStatement = values.painStatement.trim();

  if (!title) errors.title = 'アイデア名を入力してください。';
  if (title.length > 80) errors.title = 'アイデア名は80文字以内で入力してください。';
  if (!ideaSummary) errors.ideaSummary = 'アイデアの概要を入力してください。';
  if (ideaSummary.length > 1000) errors.ideaSummary = 'アイデアの概要は1000文字以内で入力してください。';
  if (!painStatement) errors.painStatement = '誰の、何のペインかを入力してください。';
  if (painStatement.length > 500) errors.painStatement = 'ペインは500文字以内で入力してください。';

  return errors;
}

export function IdeaForm({ initialValue = EMPTY_IDEA, isSubmitting = false, onSubmit }) {
  const [values, setValues] = useState(initialValue);
  const [errors, setErrors] = useState({});

  function updateValue(event) {
    const { name, value } = event.target;
    setValues((current) => ({ ...current, [name]: value }));
  }

  function handleSubmit(event) {
    event.preventDefault();
    const nextErrors = validateIdea(values);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;

    onSubmit({
      title: values.title.trim(),
      ideaSummary: values.ideaSummary.trim(),
      painStatement: values.painStatement.trim(),
    });
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="rounded-3xl border border-stone-200 bg-white p-6 shadow-sm">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold">アイデアを登録する</h2>
          <p className="mt-1 text-sm leading-6 text-stone-600">まずは判断の起点になる3項目だけを記録します。</p>
        </div>
        <span className="rounded-full bg-emerald-100 px-3 py-1 text-xs font-bold text-emerald-800">下書き</span>
      </div>

      <div className="mt-6 grid gap-5">
        <Field label="アイデア名" name="title" error={errors.title}>
          <input
            id="title"
            name="title"
            value={values.title}
            onChange={updateValue}
            maxLength={80}
            aria-invalid={Boolean(errors.title)}
            aria-describedby={errors.title ? 'title-error' : undefined}
            className="mt-2 w-full rounded-xl border border-stone-300 bg-white px-4 py-3 text-base outline-none focus:border-emerald-700 focus:ring-2 focus:ring-emerald-100"
            placeholder="例：小規模工場の設備保全ノート"
          />
        </Field>

        <Field label="アイデアの概要" name="ideaSummary" error={errors.ideaSummary}>
          <textarea
            id="ideaSummary"
            name="ideaSummary"
            value={values.ideaSummary}
            onChange={updateValue}
            maxLength={1000}
            rows={4}
            aria-invalid={Boolean(errors.ideaSummary)}
            aria-describedby={errors.ideaSummary ? 'ideaSummary-error' : undefined}
            className="mt-2 w-full resize-y rounded-xl border border-stone-300 bg-white px-4 py-3 text-base outline-none focus:border-emerald-700 focus:ring-2 focus:ring-emerald-100"
            placeholder="誰に、どんな方法で価値を届ける案か"
          />
        </Field>

        <Field label="誰の、何のペインか" name="painStatement" error={errors.painStatement}>
          <textarea
            id="painStatement"
            name="painStatement"
            value={values.painStatement}
            onChange={updateValue}
            maxLength={500}
            rows={3}
            aria-invalid={Boolean(errors.painStatement)}
            aria-describedby={errors.painStatement ? 'painStatement-error' : 'painStatement-help'}
            className="mt-2 w-full resize-y rounded-xl border border-stone-300 bg-white px-4 py-3 text-base outline-none focus:border-emerald-700 focus:ring-2 focus:ring-emerald-100"
            placeholder="例：設備保全担当者が、過去の故障対応を探せず復旧判断に時間を失う"
          />
          {!errors.painStatement && (
            <p id="painStatement-help" className="mt-2 text-xs leading-5 text-stone-500">
              対象者と、失う・恐れる・避けたいことを一文にします。
            </p>
          )}
        </Field>
      </div>

      <div className="mt-6 flex flex-wrap items-center gap-4">
        <button
          type="submit"
          disabled={isSubmitting}
          className="rounded-full bg-emerald-800 px-6 py-3 font-bold text-white hover:bg-emerald-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-800 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {isSubmitting ? '登録中…' : '下書きを登録'}
        </button>
        <p className="text-xs text-stone-500">この段階では外部サービスへ送信しません。</p>
      </div>
    </form>
  );
}

function Field({ children, error, label, name }) {
  return (
    <div>
      <label htmlFor={name} className="text-sm font-bold text-stone-800">
        {label}
      </label>
      {children}
      {error && (
        <p id={`${name}-error`} role="alert" className="mt-2 text-sm font-medium text-red-700">
          {error}
        </p>
      )}
    </div>
  );
}
