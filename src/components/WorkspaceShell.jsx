import { useEffect, useRef, useState } from 'react';
import { Archive, RotateCcw } from 'lucide-react';
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

function HistoryAction({ label, pending, restore = false, reveal = true, onClick }) {
  const Icon = restore ? RotateCcw : Archive;
  const pendingLabel = restore ? '復元中…' : '処理中…';
  const accessibleLabel = pending ? pendingLabel : label;
  return <button type="button" disabled={pending} aria-label={accessibleLabel} title={accessibleLabel} aria-live="polite" className={`workspace-shell__history-action${reveal ? ' workspace-shell__history-action--reveal' : ''}`} onClick={onClick}><Icon size={16} aria-hidden="true" /><span className="sr-only">{accessibleLabel}</span></button>;
}

function NavItems({ activePage, onSelect }) {
  return SHELL_NAV.map((item) => (
    <button key={item.id} type="button" className="workspace-shell__nav-item" aria-current={activePage === item.id ? 'page' : undefined} onClick={() => onSelect(item.id)}>
      <span aria-hidden="true" className="workspace-shell__nav-mark" />
      {item.label}
    </button>
  ));
}

export function WorkspaceShell({ activePage, onSelect, portfolio = {}, portfolioError = '', onArchive, onRestore, onOpenPortfolioItem, currentPlan = 'Free', accountContent = null, onOpenProfile, children, initialDrawerOpen = false }) {
  const [drawerOpen, setDrawerOpen] = useState(initialDrawerOpen);
  const [allOpen, setAllOpen] = useState(null);
  const [archivePending, setArchivePending] = useState('');
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
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
  async function restoreItem(type, entry) {
    const pendingKey = `${type}:${entry.id}`;
    if (archivePending) return;
    setArchivePending(pendingKey);
    try { await onRestore?.(type, entry); } finally { setArchivePending(''); }
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
            return <section key={item.id} className="py-2"><p className="px-2 text-xs font-semibold text-[var(--color-text-muted)]">{item.label}</p>{entries.slice(0, visibleLimit).map((entry) => <div key={entry.id} className="workspace-shell__history-row group"><button type="button" className="workspace-shell__history-title hover:underline" title={entry.title} aria-label={entry.title} onClick={() => { void openPortfolioItem(item.id, entry); }}>{entry.title}{item.id === 'knowledge' && entry.unread && <span className="ml-1 inline-block size-1.5 rounded-full bg-[var(--color-primary)] motion-safe:animate-pulse" aria-label="新着" />}</button>{(item.id === 'home' || item.id === 'project') && <HistoryAction pending={Boolean(archivePending)} label={`${entry.title}をアーカイブ`} onClick={() => { void archiveItem(item.id, entry.id); }} />}</div>)}{entries.length > visibleLimit && <button type="button" className="ml-2 px-2 py-1 text-xs font-medium text-[var(--color-primary)] hover:underline" onClick={() => setAllOpen(item.id)}>すべて表示</button>}</section>;
          })}
          {['home', 'project'].map((type) => {
            const archived = (portfolio[type] ?? []).filter((entry) => entry.archived);
            if (!archived.length) return null;
            return <section key={`${type}-archive`} className="py-2"><p className="px-2 text-xs font-semibold text-[var(--color-text-muted)]">アーカイブ · {SHELL_NAV.find((item) => item.id === type)?.label}</p>{archived.map((entry) => <div key={entry.id} className="workspace-shell__history-row group"><span className="workspace-shell__history-title text-[var(--color-text-muted)]" title={entry.title}>{entry.title}</span><HistoryAction pending={Boolean(archivePending)} restore label={`${entry.title}を再開`} onClick={() => { void restoreItem(type, entry); }} /></div>)}</section>;
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
                <DropdownMenuItem onSelect={() => setSettingsOpen(true)} onClick={() => setSettingsOpen(true)}>設定</DropdownMenuItem>
                <DropdownMenuItem onSelect={() => setShortcutsOpen(true)} onClick={() => setShortcutsOpen(true)}>ヘルプ・ショートカット</DropdownMenuItem>
                <DropdownMenuSeparator className="my-1 h-px bg-[var(--color-border-subtle)]" />
                <DropdownMenuItem disabled>ログアウト（認証連携前）</DropdownMenuItem>
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
            {(portfolio[allOpen] ?? []).filter((entry) => !entry.archived).map((entry) => <div key={entry.id} className="flex items-center gap-2 rounded-lg px-2 py-2 hover:bg-[var(--color-muted)]"><Button type="button" variant="ghost" className="min-w-0 flex-1 justify-start truncate" title={entry.title} onClick={() => { void openPortfolioItem(allOpen, entry); setAllOpen(null); }}>{entry.title}</Button>{(allOpen === 'home' || allOpen === 'project') && <HistoryAction reveal={false} pending={Boolean(archivePending)} label={`${entry.title}をアーカイブ`} onClick={() => { void archiveItem(allOpen, entry.id); }} />}</div>)}
          </div>
        </DialogContent>
      </Dialog>
      <Dialog open={settingsOpen} onOpenChange={setSettingsOpen}>
        <DialogContent onCloseAutoFocus={(event) => { event.preventDefault(); accountTriggerRef.current?.focus(); }}><DialogTitle>設定</DialogTitle><p className="mt-3 text-sm leading-6 text-[var(--color-text-muted)]">通知と認証連携は準備中です。プランと利用状況はアカウントメニューから開けます。</p></DialogContent>
      </Dialog>
      <Dialog open={shortcutsOpen} onOpenChange={setShortcutsOpen}>
        <DialogContent onCloseAutoFocus={(event) => { event.preventDefault(); accountTriggerRef.current?.focus(); }}><DialogTitle>ヘルプ・ショートカット</DialogTitle><dl className="mt-4 space-y-2 text-sm"><div><dt className="font-semibold">Alt + Shift + 1</dt><dd>ホームを開く</dd></div><div><dt className="font-semibold">Alt + Shift + 2</dt><dd>プロジェクトを開く</dd></div><div><dt className="font-semibold">Alt + Shift + 3</dt><dd>ナレッジを開く</dd></div><div><dt className="font-semibold">Escape</dt><dd>メニューまたはダイアログを閉じる</dd></div></dl></DialogContent>
      </Dialog>
    </div>
  );
}
