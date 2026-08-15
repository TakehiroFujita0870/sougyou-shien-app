import '../src/styles.css';

/** @type {import('@storybook/react-vite').Preview} */
const preview = {
  parameters: {
    layout: 'fullscreen',
    backgrounds: { disable: true },
  },
  decorators: [
    (Story) => <div className="Dots-shell min-h-screen"><Story /></div>,
  ],
};

export default preview;
