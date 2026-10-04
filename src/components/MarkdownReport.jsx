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

function compactBareUrl(url) {
  const parsed = new URL(url);
  const lastPathPart = parsed.pathname.split('/').filter(Boolean).at(-1);
  if (!lastPathPart) return parsed.hostname;
  const characters = Array.from(lastPathPart);
  const shortPath = characters.length > 32 ? `${characters.slice(0, 32).join('')}…` : lastPathPart;
  return `${parsed.hostname} / ${shortPath}`;
}

function headingText(children) {
  if (typeof children === 'string' || typeof children === 'number') return String(children);
  if (Array.isArray(children)) return children.map(headingText).join('');
  return children?.props ? headingText(children.props.children) : '';
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

export function MarkdownReport({ markdown, chapterHeadings = [] }) {
  const isChapterHeading = (children) => chapterHeadings.includes(headingText(children).trim());
  return <div className="markdown-report" aria-label="保存したレポート">
    <ReactMarkdown skipHtml remarkPlugins={[remarkGfm]} components={{
      h1({ children }) {
        return <h3 className={isChapterHeading(children) ? 'markdown-report__chapter-heading' : 'markdown-report__title-heading'}>{children}</h3>;
      },
      h2({ children }) {
        return isChapterHeading(children)
          ? <h3 className="markdown-report__chapter-heading">{children}</h3>
          : <h4 className="markdown-report__subheading">{children}</h4>;
      },
      h3({ children }) {
        return <h5 className="markdown-report__subheading">{children}</h5>;
      },
      h4({ children }) {
        return <h6 className="markdown-report__subheading">{children}</h6>;
      },
      h5({ children }) {
        return <h6 className="markdown-report__subheading">{children}</h6>;
      },
      h6({ children }) {
        return <h6 className="markdown-report__subheading">{children}</h6>;
      },
      a({ href, children }) {
        const url = safePublicCitationUrl(href);
        if (!url) return <span>{children}</span>;
        const linkText = typeof children === 'string' ? children
          : Array.isArray(children) && children.every((child) => typeof child === 'string') ? children.join('') : null;
        const isBareUrl = linkText?.trim() === href || linkText?.trim() === url;
        return <a href={url} title={isBareUrl ? url : undefined} target="_blank" rel="noopener noreferrer">{isBareUrl ? compactBareUrl(url) : children} <span aria-hidden="true">↗</span></a>;
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
