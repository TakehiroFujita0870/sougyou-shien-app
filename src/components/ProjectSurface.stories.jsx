import { ProjectSurface } from './ProjectSurface';

export default { title: 'Kadode/ProjectSurface', component: ProjectSurface, parameters: { layout: 'padded', a11y: { test: 'error' } } };
export const Desktop = { args: { state: 'populated' } };
export const Mobile390 = { args: { state: 'populated' }, parameters: { viewport: { defaultViewport: 'mobile1' } } };
export const Empty = { args: { state: 'empty' } };
export const Loading = { args: { state: 'loading' } };
export const Error = { args: { state: 'error' } };
