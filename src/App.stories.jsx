import { App } from './App';
import { WorkspaceShell } from './components/WorkspaceShell';

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

export const HighContrast = {
  render: () => <div className="kadode-high-contrast"><App /></div>,
};

export const Collapsed = {
  render: () => <WorkspaceShell initialCollapsed activePage="ideas" onSelect={() => {}}><h1>折りたたみ状態</h1></WorkspaceShell>,
};

export const MobileDrawer = {
  parameters: { viewport: { defaultViewport: 'mobile1' } },
  render: () => <WorkspaceShell initialDrawerOpen activePage="ideas" onSelect={() => {}}><h1>モバイルドロワー</h1></WorkspaceShell>,
};

export const Keyboard = {
  render: () => <WorkspaceShell activePage="research" onSelect={() => {}}><h1>キーボード操作</h1></WorkspaceShell>,
};
