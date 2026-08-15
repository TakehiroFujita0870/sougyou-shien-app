import { HomeSupervisor } from './HomeSupervisor';

const recovered = { messages: [{ role: 'user', content: '再試行で復元した会話' }], proposals: [] };
let loadAttempts = 0;
let storedDraft = '';
const retryRepository = {
  async load() {
    loadAttempts += 1;
    if (loadAttempts <= 2) throw new Error('offline');
    await new Promise((resolve) => setTimeout(resolve, 400));
    return recovered;
  },
  async loadDraft() { return storedDraft; },
  async save(value) { return value; },
  async saveDraft(value) { storedDraft = value; return value; },
};

export default { title: 'Dots./HomeSupervisor', component: HomeSupervisor };

export const RetryableHydrationError = { args: { repository: retryRepository } };
