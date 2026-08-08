import { App } from './App';

export default {
  title: 'Kadode/App',
  component: App,
  parameters: {
    layout: 'fullscreen',
    a11y: { test: 'error', options: { runOnly: ['wcag2a', 'wcag2aa'] } },
  },
};

export const Desktop = {};

export const Mobile = {
  parameters: { viewport: { defaultViewport: 'mobile1' } },
};
