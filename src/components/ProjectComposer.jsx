import { useState } from "react";
import { ArrowUp, Sparkles } from "lucide-react";
import { Button } from "./ui/Button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "./ui/DropdownMenu";

/**
 * Project's narrow adapter for the shared `kadode-composer` visual contract.
 * Conversation persistence remains owned by ProjectSurface.
 */
export function ProjectComposer({
  disabled,
  onCompleteDraft,
  onSubmit,
  modelKey,
  models,
  onModelChange,
}) {
  const [message, setMessage] = useState("");
  const modelLabel =
    models.find((model) => model.logicalKey === modelKey)?.displayName ??
    "GPT-5.6 Terra";
  const submit = () => {
    const next = message.trim();
    if (!next || disabled) return;
    onSubmit(next);
    setMessage("");
  };

  return (
    <form
      className="kadode-composer kadode-composer--anchored"
      aria-label="Project Kadode AI composer"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <label htmlFor="project-composer" className="sr-only">
        このプロジェクトについて Kadode AI に尋ねる
      </label>
      <textarea
        id="project-composer"
        disabled={disabled}
        className="kadode-composer__textarea kadode-composer__textarea--compact resize-none placeholder:text-[var(--color-text-muted)] disabled:cursor-wait"
        value={message}
        onChange={(event) => setMessage(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            submit();
          }
        }}
        placeholder={
          disabled
            ? "会話を読み込んでいます…"
            : "検討したい事業案を簡単に教えてください"
        }
      />
      <div className="kadode-composer__actions">
        <Button
          type="button"
          variant="ghost"
          onClick={() => setMessage((value) => onCompleteDraft(value))}
          className="min-h-9 gap-1 px-2 text-xs"
          disabled={disabled}
        >
          <Sparkles className="size-4" aria-hidden="true" />
          AIで補完
        </Button>
        <div className="flex items-center gap-1">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                className="min-h-9 px-2 text-xs"
                disabled={disabled}
                aria-label={`モデル: ${modelLabel}`}
              >
                {modelLabel}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" aria-label="AIモデルを選ぶ">
              <DropdownMenuLabel>AIモデル</DropdownMenuLabel>
              {models.map((model) => (
                <DropdownMenuItem
                  key={model.logicalKey}
                  onSelect={() => onModelChange(model.logicalKey)}
                >
                  {model.displayName}
                  {model.logicalKey === modelKey ? " ✓" : ""}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
          <Button
            type="submit"
            disabled={disabled || !message.trim()}
            className="min-h-9 rounded-lg px-3"
            aria-label="送信"
          >
            <ArrowUp className="size-4" />
          </Button>
        </div>
      </div>
    </form>
  );
}
