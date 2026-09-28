import { useEffect, useId, useState } from 'react';
import DOMPurify from 'dompurify';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { safePublicCitationUrl } from '../runtime/publicCitationUrl.js';
import './MarkdownReport.css';

function safePublicImageUrl(value) {
  const safe = safePublicCitationUrl(value);
  if (!safe) return null;
  const url = new URL(safe);
  const host = url.hostname.toLowerCase();
  if (url.protocol !== 'https:' || host === 'localhost' || host.endsWith('.local')
    || host.endsWith('.internal') || host.startsWith('[') || /^\d+\.\d+\.\d+\.\d+$/.test(host)) return null;
  return safe;
}

function MermaidDiagram({ source }) {
  const id = useId().replace(/[^a-zA-Z0-9]/g, '');
  const [view, setView] = useState({ status: 'loading', svg: '' });
  useEffect(() => {
    let active = true;
    if (source.length > 6_000) {
      setView({ status: 'failed', svg: '' });
      return undefined;
    }
    import('mermaid').then(async ({ default: mermaid }) => {
      mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme: 'dark', flowchart: { htmlLabels: false }, suppressErrorRendering: true });
      const { svg } = await mermaid.render(`dotsreport${id}`, source);
      if (active) setView({ status: 'ready', svg: DOMPurify.sanitize(svg, { USE_PROFILES: { svg: true, svgFilters: true }, FORBID_TAGS: ['foreignObject'] }) });
    }).catch(() => { if (active) setView({ status: 'failed', svg: '' }); });
    return () => { active = false; };
  }, [id, source]);
  if (view.status === 'failed') return <pre className="markdown-report__diagram-fallback"><code>{source}</code></pre>;
  if (view.status === 'loading') return <p role="status">図を描画しています…</p>;
  return <figure className="markdown-report__diagram" role="img" aria-label="レポート内の図"><div dangerouslySetInnerHTML={{ __html: view.svg }} /></figure>;
}

export function MarkdownReport({ markdown }) {
  return <div className="markdown-report" aria-label="保存したレポート">
    <ReactMarkdown skipHtml remarkPlugins={[remarkGfm]} components={{
      a({ href, children }) {
        const url = safePublicCitationUrl(href);
        return url ? <a href={url} target="_blank" rel="noopener noreferrer">{children} <span aria-hidden="true">↗</span></a> : <span>{children}</span>;
      },
      img({ src, alt }) {
        const url = safePublicImageUrl(src);
        return url ? <span className="markdown-report__image"><img src={url} alt={alt || 'レポートの画像'} loading="lazy" referrerPolicy="no-referrer" /><span className="markdown-report__image-caption">{alt || 'レポートの画像'}</span></span> : <span>{alt || '表示できない画像'}</span>;
      },
      pre({ children }) {
        const child = Array.isArray(children) ? children[0] : children;
        if (child?.props?.className === 'language-mermaid') return <MermaidDiagram source={String(child.props.children).replace(/\n$/, '')} />;
        return <pre>{children}</pre>;
      },
    }}>{markdown}</ReactMarkdown>
  </div>;
}
