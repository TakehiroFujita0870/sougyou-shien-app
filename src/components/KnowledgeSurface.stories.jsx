import fixture from '../fixtures/knowledge-admin-demo.json';
import { KnowledgeSurface } from './KnowledgeSurface';

export default { title: 'Kadode/KnowledgeSurface', component: KnowledgeSurface, parameters: { layout: 'centered', a11y: { test: 'error' } } };
export const Desktop = { args: { fixture } };
export const Mobile = { args: { fixture }, parameters: { viewport: { defaultViewport: 'mobile1' } } };
export const Empty = { args: { fixture: null } };
export const Loading = { args: { fixture: { ...fixture, asset: { ...fixture.asset, state: 'processing' } } } };
export const Error = { args: { fixture: { ...fixture, asset: { ...fixture.asset, state: 'failed' } } } };
