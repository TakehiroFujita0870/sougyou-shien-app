import { ProjectSurface } from './ProjectSurface';
import { WorkspaceShell } from './WorkspaceShell';
import { demoProjectFixture } from './projectDemoFixtureAdapter';

function retryableConversationRepository() {
  let retries = 0;
  const draftKey = 'kadode:storybook:project-hydration-draft';
  return {
    async load() { throw new Error('Injected Project hydration failure'); },
    async retryLoad() { retries += 1; if (retries === 1) throw new Error('Still offline'); await new Promise((resolve) => setTimeout(resolve, 600)); return [{ id: 'restored', role: 'assistant', content: '復元したProject会話' }]; },
    async save(messages) { return messages; },
    async loadDraft() { return localStorage.getItem(draftKey) ?? ''; },
    async saveDraft(value) { localStorage.setItem(draftKey, value); return value; },
  };
}

export default { title: 'Kadode/ProjectSurface', component: ProjectSurface, parameters: { layout: 'padded', a11y: { test: 'error' } } };
export const Desktop = { args: { state: 'populated' } };
export const Mobile390 = { args: { state: 'populated' }, parameters: { viewport: { defaultViewport: 'mobile1' } } };
export const Empty = { args: { state: 'empty' } };
export const Loading = { args: { state: 'loading' } };
export const Error = { args: { state: 'error' } };
export const HydrationRecovery = { render: () => <WorkspaceShell activePage="project" onSelect={() => {}}><div className="px-5 py-8"><ProjectSurface project={demoProjectFixture} conversationRepository={retryableConversationRepository()} /></div></WorkspaceShell>, parameters: { layout: 'fullscreen' } };
