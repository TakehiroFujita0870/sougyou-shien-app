import { fn } from 'storybook/test';

import { PlanSelection } from './PlanSelection';

export default { title: 'Kadode/PlanSelection', component: PlanSelection, args: { onApplyPlan: fn() } };

export const Free = { args: { currentPlan: 'free' } };
export const Standard = { args: { currentPlan: 'standard' } };
export const ProComingSoon = { args: { currentPlan: 'free' } };
const planViewports = {
  planDesktop: { name: 'Plan desktop', styles: { width: '1280px', height: '900px' }, type: 'desktop' },
  planMobile390: { name: 'Plan 390px', styles: { width: '390px', height: '844px' }, type: 'mobile' },
};

export const Desktop = { args: { currentPlan: 'free' }, parameters: { viewport: { defaultViewport: 'planDesktop', viewports: planViewports } } };
export const Mobile = { args: { currentPlan: 'free' }, parameters: { viewport: { defaultViewport: 'planMobile390', viewports: planViewports } } };
