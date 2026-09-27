import '../src/styles.css';

/** @type {import('@storybook/react-vite').Preview} */
const preview = {
  parameters: {
    layout: 'fullscreen',
    backgrounds: { disable: true },
    viewport: {
      defaultViewport: 'dotsPc1280',
      viewports: {
        dotsPc1280: { name: 'Dots. PC 1280 × 720 (16:9)', styles: { width: '1280px', height: '720px' }, type: 'desktop' },
      },
    },
  },
  decorators: [
    (Story) => <div className="Dots-shell min-h-screen"><Story /></div>,
  ],
};

export default preview;
