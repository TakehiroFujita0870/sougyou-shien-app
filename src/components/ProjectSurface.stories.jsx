import { ProjectSurface, projectFixture } from './ProjectSurface';

export default { title: 'Kadode/ProjectSurface', component: ProjectSurface, parameters: { layout: 'padded', a11y: { test: 'error' } } };
export const Desktop = {};
export const Mobile = { parameters: { viewport: { defaultViewport: 'mobile1' } } };
export const Empty = { args: { state: 'empty' } };
export const Populated = { args: { state: 'populated', project: { ...projectFixture, name: '現場改善ノート', status: '確認済み', sections: { 'どんな事業': '設備保全の記録を整理します。', 市場: '製造現場向けです。', 競合: '既存表計算との差分を確認中です。', 利益: '導入価値を確認中です。', 実現性: '小さく検証します。' } } } };
export const Loading = { args: { state: 'loading' } };
export const Error = { args: { state: 'error' } };
