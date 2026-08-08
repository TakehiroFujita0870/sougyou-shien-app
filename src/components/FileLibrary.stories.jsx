import { FileLibrary, createFakeDocumentRepository } from './FileLibrary';

const documents = [{ id: 'ready', name: '事業仮説.pdf', version: 1, state: 'searchable' }, { id: 'failed', name: 'メモ.csv', version: 1, state: 'failed' }];
export default { title: 'Kadode/FileLibrary', component: FileLibrary, parameters: { layout: 'centered', a11y: { test: 'error' } } };
export const Desktop = { args: { repository: createFakeDocumentRepository(documents), initialDocuments: documents } };
export const Mobile = { args: { repository: createFakeDocumentRepository(documents), initialDocuments: documents }, parameters: { viewport: { defaultViewport: 'mobile1' } } };
export const Empty = { args: { repository: createFakeDocumentRepository() } };
