import fixture from '../fixtures/knowledge-admin-demo.json';
import { KnowledgeSurface } from './KnowledgeSurface';
import { WorkspaceShell } from './WorkspaceShell';
import { createKnowledgeMetadataRepository, KNOWLEDGE_STORAGE_KEY } from './knowledgeMetadataRepository';

const localMetadataStorage = {
  getItem: (key) => key === KNOWLEDGE_STORAGE_KEY ? JSON.stringify({ documents: [{ id: 'local-file:interview.docx:2048:1', ownerId: 'admin-demo-owner', spaceId: 'admin-demo-space', name: 'interview.docx', version: 1, state: 'metadata_only', mediaType: 'docx', sizeBytes: 2048, lastModified: 1 }] }) : null,
  setItem: () => {},
};
const localMetadataRepository = createKnowledgeMetadataRepository({ ownerId: 'admin-demo-owner', spaceId: 'admin-demo-space', storage: localMetadataStorage });
let rejectFirstKnowledgeSave = true;
const writeFailureConversationRepository = {
  async load() { return { messages: [], entries: [] }; },
  async save(value) {
    if (rejectFirstKnowledgeSave) {
      rejectFirstKnowledgeSave = false;
      await new Promise((resolve) => setTimeout(resolve, 300));
      throw new Error('Injected Knowledge write failure');
    }
    return value;
  },
};
let rejectFirstMetadataDelete = true;
const removableMetadata = { id: 'local-file:write-failure.pdf', name: 'write-failure.pdf', state: 'metadata_only', mediaType: 'pdf', sizeBytes: 1024, lastModified: 1 };
const writeFailureMetadataRepository = {
  async load() {},
  list() { return rejectFirstMetadataDelete ? [removableMetadata] : []; },
  async delete() {
    if (rejectFirstMetadataDelete) {
      await new Promise((resolve) => setTimeout(resolve, 300));
      rejectFirstMetadataDelete = false;
      throw new Error('Injected Knowledge delete failure');
    }
  },
};
const hydrationMetadata = { id: 'local-file:hydration.pdf', name: 'hydration.pdf', state: 'metadata_only', mediaType: 'pdf', sizeBytes: 1024, lastModified: 1 };
const hydrationMetadataRepository = { async load() { return [hydrationMetadata]; }, list() { return [hydrationMetadata]; }, getLastError() { return null; } };
const hydrationConversationRepository = {
  async load() { throw new Error('Injected Knowledge hydration failure'); },
  async retryLoad() { await new Promise((resolve) => setTimeout(resolve, 600)); return { messages: [{ role: 'user', content: '復元した会話', createdAt: null }], entries: [] }; },
  async save(value) { return value; },
  getLastError() { return null; },
};

export default { title: 'Dots./KnowledgeSurface', component: KnowledgeSurface, parameters: { layout: 'centered', a11y: { test: 'error' } } };
export const Desktop = { args: { fixture } };
export const Mobile = { args: { fixture }, parameters: { viewport: { defaultViewport: 'mobile1' } } };
export const Empty = { args: { fixture: null } };
export const LocalMetadata = { args: { fixture, repository: localMetadataRepository } };
export const WriteFailureRecovery = { render: () => <KnowledgeSurface fixture={fixture} conversationRepository={writeFailureConversationRepository} /> };
export const WriteFailureRemoval = { render: () => <KnowledgeSurface fixture={fixture} repository={writeFailureMetadataRepository} /> };
export const HydrationRecovery = { render: () => <WorkspaceShell activePage="knowledge" onSelect={() => {}}><div className="px-5 py-8"><KnowledgeSurface fixture={fixture} repository={hydrationMetadataRepository} conversationRepository={hydrationConversationRepository} /></div></WorkspaceShell>, parameters: { layout: 'fullscreen' } };
export const Loading = { args: { fixture: { ...fixture, asset: { ...fixture.asset, state: 'processing' } } } };
export const Error = { args: { fixture: { ...fixture, asset: { ...fixture.asset, state: 'failed' } } } };
