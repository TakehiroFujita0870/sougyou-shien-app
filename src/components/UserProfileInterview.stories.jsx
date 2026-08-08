import { PROFILE_STEPS, UserProfileInterview } from './UserProfileInterview';
const values = Object.fromEntries(PROFILE_STEPS.map(([key]) => [key, 'サンプル回答']));
const repository = (saved = null, fails = false) => ({ load: async () => saved, save: async (value) => { if (fails) throw new Error('offline'); return value; } });
export default { title: 'Kadode/UserProfileInterview', component: UserProfileInterview, parameters: { layout: 'centered' } };
export const Desktop = { args: { repository: repository() } };
export const Mobile = { args: { repository: repository() }, parameters: { viewport: { defaultViewport: 'mobile1' } } };
export const Resume = { args: { repository: repository({ values, step: 3, status: 'in_progress' }) } };
export const Error = { args: { repository: repository(null, true) } };
