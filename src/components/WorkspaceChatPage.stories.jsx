import { WorkspaceChatPage } from './WorkspaceChatPage';

export default { title: 'Kadode/WorkspaceChatPage', component: WorkspaceChatPage, parameters: { a11y: { test: 'error', options: { runOnly: ['wcag2a', 'wcag2aa'] } } } };

export const Desktop = { args: { currentPage: '資料', profileReady: true, knowledge: [{ id: 'memo', kind: 'research', sourceId: 'research-1', locator: '段落 2' }] } };

export const Mobile = { args: { currentPage: '事業のタネ' }, parameters: { viewport: { defaultViewport: 'mobile1' } } };
