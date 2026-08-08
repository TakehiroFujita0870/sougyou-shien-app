import { fn } from 'storybook/test';

import { ModelSelector } from './ModelSelector';

export default {
  title: 'Kadode/ModelSelector',
  component: ModelSelector,
  args: {
    onModelChange: fn(),
    onReasoningModeChange: fn(),
  },
};

export const Free = {
  args: {
    plan: 'free',
    selectedModelKey: 'claude-haiku-4-5',
  },
};

export const Standard = {
  args: {
    plan: 'standard',
    selectedModelKey: 'gpt-5.6-terra',
    selectedReasoningMode: 'medium',
  },
};
