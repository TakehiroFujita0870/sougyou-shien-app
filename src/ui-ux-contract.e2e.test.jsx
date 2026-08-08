import { describe, it } from 'vitest';

describe('UI UX contract: intentionally failing acceptance scenarios', () => {
  it.todo('FAIL-UX-01: portfolio steward is available from every page while each conversation stays project-scoped');
  it.todo('FAIL-UX-02: conversation preview supports adopt, reasoned reject, and non-forced hold; rejection suppresses unchanged re-proposals');
  it.todo('FAIL-UX-03: same-user-space knowledge is always available and approved attachments are reusable in another page and project');
  it.todo('FAIL-UX-04: slow hydration keeps saved profile, conversation, preview, and library state through F5');
  it.todo('FAIL-UX-05: the full path is operable at 1280px and 390px with keyboard and screen reader semantics');
  it.todo('FAIL-UX-06: giant hero, separate IdeaForm, and local-fake warning do not block the primary path; telemetry stays PII-free');
});
