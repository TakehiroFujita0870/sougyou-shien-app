import { useEffect, useState } from 'react';

export const SHELL_NAV = [
  { id: 'home', label: 'Home' },
  { id: 'project', label: 'Project' },
  { id: 'knowledge', label: 'Knowledge' },
];

const PLAN_LABELS = { free: 'Free', standard: 'Standard' };

function NavItems({ activePage, onSelect }) {
  return SHELL_NAV.map((item) => (
    <button key={item.id} type="button" className="workspace-shell__nav-item" aria-current={activePage === item.id ? 'page' : undefined} onClick={() => onSelect(item.id)}>
      <span aria-hidden="true" className="workspace-shell__nav-mark" />
      {item.label}
    </button>
  ));
}

export function WorkspaceShell({ activePage, onSelect, currentPlan = 'Free', accountContent = null, onOpenProfile, children, initialCollapsed = false, initialDrawerOpen = false }) {
  const [collapsed, setCollapsed] = useState(initialCollapsed);
  const [drawerOpen, setDrawerOpen] = useState(initialDrawerOpen);
  const [accountOpen, setAccountOpen] = useState(false);

  useEffect(() => {
    const closeOnEscape = (event) => {
      if (event.key === 'Escape') setDrawerOpen(false);
    };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, []);

  function choosePage(page) {
    onSelect(page);
    setDrawerOpen(false);
  }

  return (
    <div className={`workspace-shell${collapsed ? ' workspace-shell--collapsed' : ''}`}>
      <button type="button" className="workspace-shell__mobile-trigger" aria-label="サイドバーを開く" aria-controls="workspace-sidebar" aria-expanded={drawerOpen} onClick={() => setDrawerOpen(true)}><span aria-hidden="true" className="workspace-shell__menu-mark" />メニュー</button>
      {drawerOpen && <button type="button" className="workspace-shell__scrim" aria-label="サイドバーを閉じる" onClick={() => setDrawerOpen(false)} />}
      <aside id="workspace-sidebar" className={`workspace-shell__sidebar${drawerOpen ? ' workspace-shell__sidebar--open' : ''}`} aria-label="ワークスペースサイドバー">
        <div className="workspace-shell__brand"><span className="workspace-shell__brand-dot" aria-hidden="true" />{!collapsed && <span>Kadode workspace</span>}</div>
        <nav className="workspace-shell__nav min-w-0" aria-label="主要ページ"><NavItems activePage={activePage} onSelect={choosePage} /></nav>
        <footer className="workspace-shell__account">
          <div className="workspace-shell__avatar" aria-hidden="true">K</div>
          {!collapsed && <div className="workspace-shell__account-copy"><button type="button" aria-label={`アカウント ${PLAN_LABELS[currentPlan] ?? currentPlan}`} aria-expanded={accountOpen} onClick={() => setAccountOpen((value) => !value)}><strong>アカウント</strong><span>{PLAN_LABELS[currentPlan] ?? currentPlan}</span></button>{accountOpen && <div role="menu" aria-label="アカウントメニュー"><button type="button" role="menuitem" onClick={onOpenProfile}>あなたの情報</button><button type="button" role="menuitem" onClick={() => choosePage('settings')}>プランと利用状況</button><button type="button" role="menuitem" onClick={() => choosePage('settings')}>設定</button><button type="button" role="menuitem">ヘルプ/ショートカット</button><button type="button" role="menuitem">ログアウト</button></div>}</div>}
        </footer>
      </aside>
      <section className="workspace-shell__main">
        {children}
      </section>
    </div>
  );
}
