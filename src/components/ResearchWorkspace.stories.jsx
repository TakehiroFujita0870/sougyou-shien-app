import { ResearchWorkspace, createLocalResearchRepository } from './ResearchWorkspace';

export default { title: 'Dots./ResearchWorkspace', component: ResearchWorkspace, parameters: { layout: 'padded' } };
export const Desktop = { args: { repository: createLocalResearchRepository() } };
export const Mobile = { args: { repository: createLocalResearchRepository() }, parameters: { viewport: { defaultViewport: 'mobile1' } } };
export const PartialFailure = { args: { repository: createLocalResearchRepository({ sourceStatus: { patent: 'timeout: retry the source', decision: 'limit: retry after 00:00 JST' } }) } };
