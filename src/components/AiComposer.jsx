import { ArrowUp } from 'lucide-react';

import { Button } from './ui/Button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuTrigger } from './ui/DropdownMenu';

export function ModelMenu({ disabled = false, modelKey, models = [], onModelChange, contentAriaLabel, showSelected = false }) {
  const modelLabel = models.find((model) => model.logicalKey === modelKey)?.displayName ?? 'GPT-5.6 Terra';
  return <DropdownMenu><DropdownMenuTrigger asChild><Button type="button" variant="ghost" className="min-h-9 px-2 text-xs" disabled={disabled} aria-label={`モデル: ${modelLabel}`}>{modelLabel}</Button></DropdownMenuTrigger><DropdownMenuContent align="end" aria-label={contentAriaLabel}><DropdownMenuLabel>AIモデル</DropdownMenuLabel>{models.map((model) => <DropdownMenuItem key={model.logicalKey} onSelect={() => onModelChange?.(model.logicalKey)}>{model.displayName}{showSelected && model.logicalKey === modelKey ? ' ✓' : ''}</DropdownMenuItem>)}</DropdownMenuContent></DropdownMenu>;
}

export function AiComposer({
  id,
  label,
  value,
  onValueChange,
  onSubmit,
  placeholder,
  disabled = false,
  rows,
  maxLength,
  mode = 'inline',
  className = '',
  outerClassName = '',
  textareaClassName = '',
  actionsClassName = '',
  formAriaLabel,
  formData = {},
  modelKey,
  models = [],
  onModelChange,
  modelMenuAriaLabel,
  showSelectedModel = false,
  sendAriaLabel = '送信',
  sendIcon = <ArrowUp className="size-4" aria-hidden="true" />,
  disableSendWhenEmpty = true,
  leadingActions = null,
  groupTrailingActions = false,
  children = null,
}) {
  const submit = (event) => {
    event?.preventDefault();
    if (disabled || (disableSendWhenEmpty && !value.trim())) return;
    onSubmit?.(value, event);
  };
  const trailing = <><ModelMenu disabled={disabled} modelKey={modelKey} models={models} onModelChange={onModelChange} contentAriaLabel={modelMenuAriaLabel} showSelected={showSelectedModel} /><Button type="submit" disabled={disabled || (disableSendWhenEmpty && !value.trim())} className={groupTrailingActions ? 'min-h-9 rounded-lg px-3' : 'min-h-9 min-w-9 px-2'} aria-label={sendAriaLabel}>{sendIcon}</Button></>;
  const content = <><label htmlFor={id} className="sr-only">{label}</label><textarea id={id} disabled={disabled} value={value} onChange={(event) => onValueChange(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) submit(event); }} rows={rows} maxLength={maxLength} className={`kadode-composer__textarea ${textareaClassName}`.trim()} placeholder={placeholder} />{children}<div className={`kadode-composer__actions ${actionsClassName}`.trim()}>{leadingActions}{groupTrailingActions ? <div className="flex items-center gap-1">{trailing}</div> : trailing}</div></>;
  const surfaceClass = `kadode-composer ${mode === 'anchored' ? 'kadode-composer--anchored' : ''} ${className}`.trim();
  return <form {...formData} aria-label={formAriaLabel} onSubmit={submit} className={outerClassName || surfaceClass}>{outerClassName ? <div className={surfaceClass}>{content}</div> : content}</form>;
}
