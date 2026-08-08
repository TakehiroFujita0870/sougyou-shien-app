export const AI_PR_DRAFT_STATUSES = {
  DRAFT: 'draft',
  REVISION_REQUESTED: 'revision_requested',
  APPROVED: 'approved',
  REJECTED: 'rejected',
};

const SENSITIVE_CONTENT_PATTERN = /(?:[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}|(?:\+81|0)\d{1,4}[-\s]?\d{1,4}[-\s]?\d{3,4}|api[_-]?key\s*[=:]|access[_-]?token\s*[=:]|authorization\s*[=:]|password\s*[=:]|secret\s*[=:]|-----BEGIN(?: [A-Z]+)? PRIVATE KEY-----)/i;
const SENSITIVE_CONTENT_MESSAGE = '個人情報または秘密情報が含まれている可能性があります。削除または置換してください。';

export function validateDraftContent(content) {
  const errors = {};
  const normalizedContent = content?.trim() ?? '';

  if (!normalizedContent) {
    errors.content = '投稿案を入力してください。';
  } else if (normalizedContent.length > 280) {
    errors.content = '投稿案は280文字以内で入力してください。';
  } else if (SENSITIVE_CONTENT_PATTERN.test(normalizedContent)) {
    errors.content = SENSITIVE_CONTENT_MESSAGE;
  }

  return errors;
}

export function createAiPublicRelationsDraftRepository() {
  let drafts = [];
  let nextId = 1;

  function save(nextDraft) {
    drafts = drafts.map((draft) => (draft.id === nextDraft.id ? nextDraft : draft));
    return nextDraft;
  }

  function find(id) {
    const draft = drafts.find((item) => item.id === id);
    if (!draft) throw new Error('対象の下書きが見つかりません。');
    return draft;
  }

  function changeStatus(id, status, decisionNote = '') {
    const noteErrors = decisionNote ? validateDraftContent(decisionNote) : {};
    if (noteErrors.content) throw new Error(noteErrors.content);

    const draft = find(id);
    return save({ ...draft, status, decisionNote: decisionNote.trim(), updatedAt: new Date().toISOString() });
  }

  return {
    create({ content }) {
      const errors = validateDraftContent(content);
      if (errors.content) throw new Error(errors.content);

      const now = new Date().toISOString();
      const draft = {
        id: `ai-pr-draft-${nextId++}`,
        content: content.trim(),
        status: AI_PR_DRAFT_STATUSES.DRAFT,
        decisionNote: '',
        createdAt: now,
        updatedAt: now,
      };
      drafts = [draft, ...drafts];
      return draft;
    },
    list() {
      return [...drafts];
    },
    requestRevision(id, note) {
      return changeStatus(id, AI_PR_DRAFT_STATUSES.REVISION_REQUESTED, note);
    },
    approve(id, note = '') {
      return changeStatus(id, AI_PR_DRAFT_STATUSES.APPROVED, note);
    },
    reject(id, note) {
      return changeStatus(id, AI_PR_DRAFT_STATUSES.REJECTED, note);
    },
  };
}
