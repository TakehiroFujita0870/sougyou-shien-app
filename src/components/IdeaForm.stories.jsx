import { fn } from 'storybook/test';

import { IdeaForm } from './IdeaForm';

export default {
  title: 'Kadode/IdeaForm',
  component: IdeaForm,
  args: { onSubmit: fn() },
};

export const Empty = {};

export const WithDraft = {
  args: {
    initialValue: {
      title: '小規模工場の設備保全ノート',
      ideaSummary: '故障履歴と復旧手順を設備ごとに構造化して残す。',
      painStatement: '設備保全担当者が、過去の故障対応を探せず復旧判断に時間を失う。',
    },
  },
};

export const Submitting = {
  args: { isSubmitting: true },
};
