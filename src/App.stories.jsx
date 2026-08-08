import { App } from './App';

export default {
  title: 'Kadode/App',
  component: App,
  parameters: { layout: 'fullscreen' },
};

export const Default = {};

export const Mobile = {
  parameters: { viewport: { defaultViewport: 'mobile1' } },
};
