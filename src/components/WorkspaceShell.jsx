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
  useEffect(() => {
    const closeAccount = (event) => { if (event.key === 'Escape') setAccountOpen(false); };
    window.addEventListener('keydown', closeAccount);
    return () => window.removeEventListener('keydown', closeAccount);
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
          {!collapsed && <div className="workspace-shell__account-copy relative"><button type="button" className="flex min-h-11 w-full items-center gap-2 rounded-xl px-2 text-left" aria-label={`アカウント ${PLAN_LABELS[currentPlan] ?? currentPlan}`} aria-expanded={accountOpen} onClick={() => setAccountOpen((value) => !value)}><span className="grid size-8 shrink-0 place-items-center rounded-full bg-stone-200 text-sm font-bold">K</span><span className="min-w-0 flex-1"><strong className="block truncate">アカウント</strong><span className="mt-0.5 inline-flex rounded-full border border-stone-300 px-1.5 py-0.5 text-[11px] font-semibold text-stone-600">{PLAN_LABELS[currentPlan] ?? currentPlan}</span></span><span aria-hidden="true" className="text-stone-500">⌄</span></button>{accountOpen && <div role="menu" aria-label="アカウントメニュー" className="absolute bottom-14 left-0 z-20 grid min-w-56 gap-1 rounded-2xl border border-stone-200 bg-white p-2 shadow-lg max-sm:fixed max-sm:inset-x-3 max-sm:bottom-3"><button type="button" role="menuitem" onClick={onOpenProfile}>あなたの情報</button><button type="button" role="menuitem" onClick={() => choosePage('settings')}>プランと利用状況</button><button type="button" role="menuitem" onClick={() => choosePage('settings')}>設定</button><button type="button" role="menuitem">ヘルプ・ショートカット</button><button type="button" role="menuitem">ログアウト</button></div>}</div>}
        </footer>
      </aside>
      <section className="workspace-shell__main">
        {children}
      </section>
    </div>
  );
}
