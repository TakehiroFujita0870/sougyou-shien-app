import fixture from '../fixtures/knowledge-admin-demo.json';
import { KnowledgeSurface } from './KnowledgeSurface';
import { createKnowledgeMetadataRepository, KNOWLEDGE_STORAGE_KEY } from './knowledgeMetadataRepository';

const localMetadataStorage = {
  getItem: (key) => key === KNOWLEDGE_STORAGE_KEY ? JSON.stringify({ documents: [{ id: 'local-file:interview.docx:2048:1', ownerId: 'admin-demo-owner', spaceId: 'admin-demo-space', name: 'interview.docx', version: 1, state: 'metadata_only', mediaType: 'docx', sizeBytes: 2048, lastModified: 1 }] }) : null,
  setItem: () => {},
};
const localMetadataRepository = createKnowledgeMetadataRepository({ ownerId: 'admin-demo-owner', spaceId: 'admin-demo-space', storage: localMetadataStorage });

export default { title: 'Kadode/KnowledgeSurface', component: KnowledgeSurface, parameters: { layout: 'centered', a11y: { test: 'error' } } };
export const Desktop = { args: { fixture } };
export const Mobile = { args: { fixture }, parameters: { viewport: { defaultViewport: 'mobile1' } } };
export const Empty = { args: { fixture: null } };
export const LocalMetadata = { args: { fixture, repository: localMetadataRepository } };
export const Loading = { args: { fixture: { ...fixture, asset: { ...fixture.asset, state: 'processing' } } } };
export const Error = { args: { fixture: { ...fixture, asset: { ...fixture.asset, state: 'failed' } } } };
