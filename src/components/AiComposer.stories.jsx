import { useState } from 'react';
import { Mic, Sparkles } from 'lucide-react';

import { AiComposer } from './AiComposer';
import { Button } from './ui/Button';

const models = [{ logicalKey: 'terra', displayName: 'GPT-5.6 Terra' }, { logicalKey: 'haiku', displayName: 'Claude Haiku 4.5' }];

function ComposerStory({ mode = 'inline', compact = false, project = false }) {
  const [value, setValue] = useState(''); const [modelKey, setModelKey] = useState('terra');
  return <div className="min-h-[420px] p-6"><AiComposer id="storybook-ai-composer" label="Kadode AIへのメッセージ" value={value} onValueChange={setValue} onSubmit={() => setValue('')} placeholder="事業について相談する" mode={mode} modelKey={modelKey} models={models} onModelChange={setModelKey} textareaClassName={compact ? 'kadode-composer__textarea--compact resize-none' : 'min-h-36 resize-none'} groupTrailingActions={project} leadingActions={project ? <Button type="button" variant="ghost" className="min-h-9 gap-1 px-2 text-xs"><Sparkles className="size-4" />AIで補完</Button> : <Button type="button" variant="ghost" disabled aria-label="音声入力（準備中）"><Mic className="size-4" /></Button>} /></div>;
}

export default { title: 'Kadode/AiComposer', component: AiComposer, parameters: { layout: 'fullscreen', a11y: { test: 'error' } } };
export const HomeInline = { render: () => <ComposerStory /> };
export const ProjectAnchored = { render: () => <ComposerStory mode="anchored" compact project /> };
export const KnowledgeAnchored = { render: () => <ComposerStory mode="anchored" compact /> };
