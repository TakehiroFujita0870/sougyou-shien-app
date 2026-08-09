import { useEffect, useRef, useState } from 'react';
import { Badge } from './ui/Badge';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from './ui/DropdownMenu';

export const SHELL_NAV = [
  { id: 'home', label: 'Home' },
  { id: 'project', label: 'Project' },
  { id: 'knowledge', label: 'Knowledge' },
];

const PLAN_LABELS = { free: 'Free', standard: 'Standard' };
const ACCOUNT_DISPLAY_NAME = 'タケヒロ';

function NavItems({ activePage, onSelect }) {
  return SHELL_NAV.map((item) => (
    <button key={item.id} type="button" className="workspace-shell__nav-item" aria-current={activePage === item.id ? 'page' : undefined} onClick={() => onSelect(item.id)}>
      <span aria-hidden="true" className="workspace-shell__nav-mark" />
      {item.label}
    </button>
  ));
}

export function WorkspaceShell({ activePage, onSelect, currentPlan = 'Free', accountContent = null, onOpenProfile, children, initialDrawerOpen = false }) {
  const [drawerOpen, setDrawerOpen] = useState(initialDrawerOpen);
  const accountTriggerRef = useRef(null);

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
    <div className="workspace-shell">
      <button type="button" className="workspace-shell__mobile-trigger" aria-label="サイドバーを開く" aria-controls="workspace-sidebar" aria-expanded={drawerOpen} onClick={() => setDrawerOpen(true)}><span aria-hidden="true" className="workspace-shell__menu-mark" />メニュー</button>
      {drawerOpen && <button type="button" className="workspace-shell__scrim" aria-label="サイドバーを閉じる" onClick={() => setDrawerOpen(false)} />}
      <aside id="workspace-sidebar" className={`workspace-shell__sidebar${drawerOpen ? ' workspace-shell__sidebar--open' : ''}`} aria-label="ワークスペースサイドバー">
        <div className="workspace-shell__brand"><span className="workspace-shell__brand-dot" aria-hidden="true" /><span>Kadode</span></div>
        <nav className="workspace-shell__nav min-w-0" aria-label="主要ページ"><NavItems activePage={activePage} onSelect={choosePage} /></nav>
        <footer className="workspace-shell__account">
          <div className="workspace-shell__account-copy">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button ref={accountTriggerRef} type="button" className="flex min-h-11 w-full items-center gap-2 rounded-xl px-2 text-left hover:bg-[var(--color-muted)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-focus)]" aria-label={`${ACCOUNT_DISPLAY_NAME}のアカウント ${PLAN_LABELS[currentPlan] ?? currentPlan}`}>
                  <span className="grid size-8 shrink-0 place-items-center rounded-full bg-stone-200 text-sm font-bold">K</span>
                  <strong className="min-w-0 flex-1 truncate">{ACCOUNT_DISPLAY_NAME}</strong>
                  <Badge variant="outline">{PLAN_LABELS[currentPlan] ?? currentPlan}</Badge>
                  <span aria-hidden="true" className="text-stone-500">⌄</span>
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent aria-label="アカウントメニュー" side="top" align="start" onCloseAutoFocus={(event) => {
                event.preventDefault();
                accountTriggerRef.current?.focus();
              }}>
                {accountContent && <div className="workspace-shell__account-auth px-1 pb-1">{accountContent}</div>}
                <DropdownMenuLabel className="px-2.5 py-1.5 text-xs font-medium text-[var(--color-text-muted)]">あなたの情報</DropdownMenuLabel>
                <DropdownMenuItem onSelect={onOpenProfile} onClick={onOpenProfile}>プロフィールを編集</DropdownMenuItem>
                <DropdownMenuSeparator className="my-1 h-px bg-[var(--color-border-subtle)]" />
                <DropdownMenuLabel className="px-2.5 py-1.5 text-xs font-medium text-[var(--color-text-muted)]">プランと利用状況</DropdownMenuLabel>
                <DropdownMenuItem onSelect={() => choosePage('settings')} onClick={() => choosePage('settings')}>プランと利用状況</DropdownMenuItem>
                <DropdownMenuSeparator className="my-1 h-px bg-[var(--color-border-subtle)]" />
                <DropdownMenuLabel className="px-2.5 py-1.5 text-xs font-medium text-[var(--color-text-muted)]">設定</DropdownMenuLabel>
                <DropdownMenuItem onSelect={() => choosePage('settings')} onClick={() => choosePage('settings')}>設定</DropdownMenuItem>
                <DropdownMenuSeparator className="my-1 h-px bg-[var(--color-border-subtle)]" />
                <DropdownMenuLabel className="px-2.5 py-1.5 text-xs font-medium text-[var(--color-text-muted)]">ヘルプ・ショートカット</DropdownMenuLabel>
                <DropdownMenuItem>ヘルプ・ショートカット</DropdownMenuItem>
                <DropdownMenuSeparator className="my-1 h-px bg-[var(--color-border-subtle)]" />
                <DropdownMenuItem>ログアウト</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </footer>
      </aside>
      <section className="workspace-shell__main">
        {children}
      </section>
    </div>
  );
}
