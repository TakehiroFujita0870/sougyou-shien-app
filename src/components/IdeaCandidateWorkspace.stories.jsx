import { IdeaCandidateWorkspace } from './IdeaCandidateWorkspace';
const item = { id: 'demo', title: '工場ノート', summary: '設備保全を記録', pain: '履歴が探せない' };
const repository = (items = [], fails = false) => ({ load: async () => items, save: async (next) => { if (fails) throw new Error('offline'); return next; } });
export default { title: 'Kadode/IdeaCandidateWorkspace', component: IdeaCandidateWorkspace, parameters: { layout: 'padded' } };
export const Desktop = { args: { repository: repository([item]) } };
export const Mobile = { args: { repository: repository([item]) }, parameters: { viewport: { defaultViewport: 'mobile1' } } };
export const SaveError = { args: { repository: repository([], true) } };
