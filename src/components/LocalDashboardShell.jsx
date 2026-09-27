import './LocalDashboardShell.css';
import dotsIcon from '../../plugins/dots/assets/dots-icon.png';

function DotsBrand() {
  return <div className="local-shell__brand" role="img" aria-label="Dots.">
    <span className="local-shell__brand-mark" aria-hidden="true"><img src={dotsIcon} alt="" /></span>
    <span className="local-shell__brand-word" aria-hidden="true"><img src={dotsIcon} alt="" /></span>
  </div>;
}

export function LocalDashboardShell({ activePage, onSelect, children }) {
  return <div className="local-shell">
    <aside className="local-shell__sidebar" aria-label="Dots. メニュー">
      <DotsBrand />
      <nav className="local-shell__nav" aria-label="メイン">
        <button type="button" aria-current={activePage === 'local-home' ? 'page' : undefined} onClick={() => onSelect('local-home')}><span aria-hidden="true">⌂</span> ホーム</button>
        <button type="button" aria-current={activePage === 'graph' ? 'page' : undefined} onClick={() => onSelect('graph')}><span aria-hidden="true">✦</span> グラフ</button>
        <button type="button" aria-current={activePage === 'local-services' ? 'page' : undefined} onClick={() => onSelect('local-services')}><span aria-hidden="true">◈</span> サービス管理</button>
      </nav>
    </aside>
    <div className="local-shell__workspace">
      <div className="local-shell__content">
        <div className="local-shell__sky" aria-hidden="true" />
        <div className="local-shell__body">{children}</div>
      </div>
    </div>
  </div>;
}

export default LocalDashboardShell;
