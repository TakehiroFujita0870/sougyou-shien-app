import { ArrowUp, Sparkles } from "lucide-react";
import { AiComposer } from "./AiComposer";
import { Button } from "./ui/Button";

/**
 * Project's narrow adapter for the shared `kadode-composer` visual contract.
 * Conversation persistence remains owned by ProjectSurface.
 */
export function ProjectComposer({
  disabled,
  loading = false,
  value = "",
  onValueChange = () => {},
  onCompleteDraft,
  onSubmit,
  modelKey,
  models,
  onModelChange,
}) {
  const submit = () => {
    const next = value.trim();
    if (!next || disabled) return;
    onSubmit(next);
    onValueChange("");
  };

  return (
    <AiComposer
      id="project-composer"
      label="このプロジェクトについて Kadode AI に尋ねる"
      value={value}
      onValueChange={onValueChange}
      onSubmit={submit}
      disabled={disabled}
      textareaDisabled={loading}
      mode="anchored"
      formAriaLabel="Project Kadode AI composer"
      textareaClassName="kadode-composer__textarea--compact resize-none placeholder:text-[var(--color-text-muted)] disabled:cursor-wait"
      placeholder={
          loading
            ? "会話を読み込んでいます…"
            : "検討したい事業案を簡単に教えてください"
        }
      modelKey={modelKey}
      models={models}
      onModelChange={onModelChange}
      modelMenuAriaLabel="AIモデルを選ぶ"
      showSelectedModel
      sendAriaLabel="送信"
      sendIcon={<ArrowUp className="size-4" />}
      disableSendWhenEmpty
      groupTrailingActions
      leadingActions={<Button
          type="button"
          variant="ghost"
          onClick={() => onValueChange(onCompleteDraft(value))}
          className="min-h-9 gap-1 px-2 text-xs"
          disabled={disabled}
        >
          <Sparkles className="size-4" aria-hidden="true" />
          AIで補完
        </Button>}
    />
  );
}
