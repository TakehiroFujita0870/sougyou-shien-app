import { AiPublicRelationsDraftWorkflow } from './AiPublicRelationsDraftWorkflow';

export default {
  title: 'Kadode/AiPublicRelationsDraftWorkflow',
  component: AiPublicRelationsDraftWorkflow,
};

export const Empty = {};

function repositoryWith(status, decisionNote = '') {
  const draft = {
    id: 'ai-pr-draft-story',
    content: '現場で得た知見を、次の検証に活かします。',
    status,
    decisionNote,
  };
  return {
    list: () => [draft],
    create: () => draft,
    requestRevision: () => draft,
    approve: () => draft,
    reject: () => draft,
  };
}

export const Draft = {
  args: { repository: repositoryWith('draft') },
};

export const RevisionRequested = {
  args: { repository: repositoryWith('revision_requested', '根拠となる事実を一文追加してください。') },
};

export const Approved = {
  args: { repository: repositoryWith('approved', '内容を確認しました。') },
};

export const Rejected = {
  args: { repository: repositoryWith('rejected', '公開方針と合わないため。') },
};
