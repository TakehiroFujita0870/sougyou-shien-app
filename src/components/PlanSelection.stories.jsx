import { fn } from 'storybook/test';

import { PlanSelection } from './PlanSelection';

export default { title: 'Kadode/PlanSelection', component: PlanSelection, args: { onApplyPlan: fn() } };

export const Free = { args: { currentPlan: 'free' } };
export const Standard = { args: { currentPlan: 'standard' } };
export const ProComingSoon = { args: { currentPlan: 'free' } };
export const Desktop = { args: { currentPlan: 'free' } };
export const Mobile = { args: { currentPlan: 'free' }, parameters: { viewport: { defaultViewport: 'mobile1' } } };
