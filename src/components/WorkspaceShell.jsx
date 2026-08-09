import { useEffect, useRef, useState } from 'react';
import { Badge } from './ui/Badge';
import { Button } from './ui/Button';
import { Dialog, DialogContent, DialogTitle } from './ui/Dialog';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from './ui/DropdownMenu';

export const SHELL_NAV = [
  { id: 'home', label: 'ホーム' },
  { id: 'project', label: 'プロジェクト' },
  { id: 'knowledge', label: 'ナレッジ' },
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

export function WorkspaceShell({ activePage, onSelect, portfolio = {}, portfolioError = '', onArchive, onOpenPortfolioItem, currentPlan = 'Free', accountContent = null, onOpenProfile, children, initialDrawerOpen = false }) {
  const [drawerOpen, setDrawerOpen] = useState(initialDrawerOpen);
  const [allOpen, setAllOpen] = useState(null);
  const [archivePending, setArchivePending] = useState('');
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
  async function openPortfolioItem(type, entry) {
    try { await onOpenPortfolioItem?.(type, entry); } catch { return; }
    if (!onOpenPortfolioItem) choosePage(type);
    else setDrawerOpen(false);
    if (type === 'knowledge') requestAnimationFrame(() => {
      const main = document.querySelector('.workspace-shell__main');
      main?.scrollTo?.({ top: 0, behavior: 'auto' });
      const heading = document.querySelector('#knowledge-heading');
      heading?.setAttribute('tabindex', '-1');
      heading?.focus?.({ preventScroll: true });
    });
  }
  async function archiveItem(type, id) {
    const pendingKey = `${type}:${id}`;
    if (archivePending) return;
    setArchivePending(pendingKey);
    try {
      const succeeded = await onArchive?.(type, id);
      if (succeeded && allOpen === type) setAllOpen(null);
    } finally {
      setArchivePending('');
    }
  }

  return (
    <div className="workspace-shell">
      <button type="button" className="workspace-shell__mobile-trigger" aria-label="サイドバーを開く" aria-controls="workspace-sidebar" aria-expanded={drawerOpen} onClick={() => setDrawerOpen(true)}><span aria-hidden="true" className="workspace-shell__menu-mark" />メニュー</button>
      {drawerOpen && <button type="button" className="workspace-shell__scrim" aria-label="サイドバーを閉じる" onClick={() => setDrawerOpen(false)} />}
      <aside id="workspace-sidebar" className={`workspace-shell__sidebar${drawerOpen ? ' workspace-shell__sidebar--open' : ''}`} aria-label="ワークスペースサイドバー">
        <div className="workspace-shell__brand"><span className="workspace-shell__brand-dot" aria-hidden="true" /><span>Kadode</span></div>
        <nav className="workspace-shell__nav min-w-0" aria-label="主要ページ"><NavItems activePage={activePage} onSelect={choosePage} /></nav>
        {portfolioError && <p role="alert" className="mx-3 rounded-lg bg-red-50 px-3 py-2 text-xs leading-5 text-red-800">{portfolioError}</p>}
        <div className="min-h-0 flex-1 overflow-y-auto px-2" aria-label="最近の項目">
          {SHELL_NAV.map((item) => {
            const entries = (portfolio[item.id] ?? []).filter((entry) => !entry.archived);
            const visibleLimit = item.id === 'knowledge' ? 5 : 10;
            return <section key={item.id} className="py-2"><p className="px-2 text-xs font-semibold text-[var(--color-text-muted)]">{item.label}</p>{entries.slice(0, visibleLimit).map((entry) => <div key={entry.id} className="ml-2 flex items-center gap-1 px-2"><button type="button" className="min-w-0 flex-1 truncate py-1.5 text-left text-xs hover:underline" onClick={() => { void openPortfolioItem(item.id, entry); }}>{entry.title}{item.id === 'knowledge' && entry.unread && <span className="ml-1 inline-block size-1.5 rounded-full bg-[var(--color-primary)] motion-safe:animate-pulse" aria-label="新着" />}</button>{(item.id === 'home' || item.id === 'project') && <button type="button" disabled={Boolean(archivePending)} aria-label={`${entry.title}をアーカイブ`} className="shrink-0 text-xs text-[var(--color-text-muted)] hover:underline disabled:opacity-50" onClick={() => { void archiveItem(item.id, entry.id); }}>{archivePending === `${item.id}:${entry.id}` ? '処理中…' : 'アーカイブ'}</button>}</div>)}{entries.length > visibleLimit && <button type="button" className="ml-2 px-2 py-1 text-xs font-medium text-[var(--color-primary)] hover:underline" onClick={() => setAllOpen(item.id)}>すべて表示</button>}</section>;
          })}
        </div>
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
                <DropdownMenuItem onSelect={onOpenProfile} onClick={onOpenProfile}>プロフィールを編集</DropdownMenuItem>
                <DropdownMenuItem onSelect={() => choosePage('settings')} onClick={() => choosePage('settings')}>プランと利用状況</DropdownMenuItem>
                <DropdownMenuSeparator className="my-1 h-px bg-[var(--color-border-subtle)]" />
                <DropdownMenuItem onSelect={() => choosePage('settings')} onClick={() => choosePage('settings')}>設定</DropdownMenuItem>
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
      <Dialog open={Boolean(allOpen)} onOpenChange={(open) => { if (!open) setAllOpen(null); }}>
        <DialogContent className="max-h-[80dvh] overflow-hidden p-0">
          <DialogTitle className="border-b border-[var(--color-border-subtle)] px-6 py-5 text-lg font-semibold">{SHELL_NAV.find((item) => item.id === allOpen)?.label}の履歴</DialogTitle>
          <div className="max-h-[calc(80dvh-5rem)] overflow-y-auto px-4 py-3" aria-label="すべての履歴">
            {(portfolio[allOpen] ?? []).filter((entry) => !entry.archived).map((entry) => <div key={entry.id} className="flex items-center gap-2 rounded-lg px-2 py-2 hover:bg-[var(--color-muted)]"><Button type="button" variant="ghost" className="min-w-0 flex-1 justify-start truncate" onClick={() => { void openPortfolioItem(allOpen, entry); setAllOpen(null); }}>{entry.title}</Button>{(allOpen === 'home' || allOpen === 'project') && <Button type="button" variant="ghost" disabled={Boolean(archivePending)} className="shrink-0 text-xs" onClick={() => { void archiveItem(allOpen, entry.id); }}>{archivePending === `${allOpen}:${entry.id}` ? '処理中…' : 'アーカイブ'}</Button>}</div>)}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
