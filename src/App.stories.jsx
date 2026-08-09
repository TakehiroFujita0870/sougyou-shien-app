import { expect, userEvent, within } from 'storybook/test';

import { App } from './App';
import { WorkspaceShell } from './components/WorkspaceShell';

const completedProfile = { values: { experience: '', strengths: '', interests: '', time: '', budget: '', avoidances: '' }, step: 5, status: 'completed', error: '' };
const profileRepository = { load: async () => completedProfile, save: async (value) => value };
const adoptedProject = { id: 'story-project', title: '地域物流の共同配送', fact: '配送頻度の偏りが固定費を押し上げている', inference: '共同配送で積載率を改善できる', reason: '事業性を検証する', status: 'adopted' };
const adoptedProjectRepository = { load: async () => adoptedProject, saveAdopted: async (value) => value };
const homeConversationRepository = { load: async () => ({ messages: [], proposals: [], input: '' }), save: async (value) => value };
const portfolioRepository = { load: async () => ({ home: [], project: [], knowledge: [] }), ensure: async () => ({ home: [], project: [], knowledge: [] }), upsert: async () => ({ home: [], project: [], knowledge: [] }), archive: async () => ({ home: [], project: [], knowledge: [] }) };
const desktop = { width: '1440px', height: '900px' };

function SurfaceStory({ surface = 'home' }) {
  window.sessionStorage.setItem('kadode:selected-surface', surface);
  return <App profileRepository={profileRepository} adoptedProjectRepository={adoptedProjectRepository} homeConversationRepository={homeConversationRepository} sidebarPortfolioRepository={portfolioRepository} />;
}

export default {
  title: 'Kadode/App',
  component: App,
  parameters: {
    layout: 'fullscreen',
    a11y: { test: 'error', options: { runOnly: ['wcag2a', 'wcag2aa'] } },
    viewport: { defaultViewport: 'desktop1440', viewports: { desktop1440: { name: 'Desktop 1440 × 900', styles: desktop, type: 'desktop' } } },
  },
};

export const Desktop = {};
export const Mobile = { parameters: { viewport: { defaultViewport: 'mobile1' } } };
export const HighContrast = { render: () => <div className="kadode-high-contrast"><App /></div> };
export const Collapsed = { render: () => <WorkspaceShell initialCollapsed activePage="ideas" onSelect={() => {}}><h1>折りたたみ状態</h1></WorkspaceShell> };
export const MobileDrawer = { parameters: { viewport: { defaultViewport: 'mobile1' } }, render: () => <WorkspaceShell initialDrawerOpen activePage="ideas" onSelect={() => {}}><h1>モバイルドロワー</h1></WorkspaceShell> };
export const Keyboard = { render: () => <WorkspaceShell activePage="research" onSelect={() => {}}><h1>キーボード操作</h1></WorkspaceShell> };

export const Home = { render: () => <SurfaceStory surface="home" /> };
export const Project = { render: () => <SurfaceStory surface="project" /> };
export const Knowledge = { render: () => <SurfaceStory surface="knowledge" /> };
export const Account = {
  render: () => <SurfaceStory surface="home" />,
  play: async ({ canvasElement }) => {
    const account = await within(canvasElement).findByRole('button', { name: /アカウント/ });
    await userEvent.click(account);
    await expect(within(document.body).getByRole('menu')).toBeVisible();
  },
};
