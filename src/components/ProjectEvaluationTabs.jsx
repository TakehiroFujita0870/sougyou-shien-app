import { useEffect, useState } from "react";
import { Badge } from "./ui/Badge";
import { Card } from "./ui/Card";

export function ProjectEvaluationTabs({ definitions, fallbackSections, project, targetView, onTargetViewHandled }) {
  const [activeIndex, setActiveIndex] = useState(0);
  useEffect(() => {
    if (!targetView) return;
    const index = definitions.findIndex(({ key, label }) => key === targetView || label === targetView);
    if (index < 0) { onTargetViewHandled?.(); return; }
    setActiveIndex(index);
    requestAnimationFrame(() => {
      document.getElementById(`project-evaluation-tab-${index}`)?.focus();
      onTargetViewHandled?.();
    });
  }, [definitions, onTargetViewHandled, targetView]);
  const activeTab = definitions[activeIndex];
  const activeSection =
    project.sections?.[activeTab.key] ??
    project.sections?.[activeTab.label] ??
    fallbackSections[activeTab.key];

  function selectFromKeyboard(event, index) {
    let nextIndex = index;
    if (event.key === "ArrowRight") nextIndex = (index + 1) % definitions.length;
    else if (event.key === "ArrowLeft")
      nextIndex = (index - 1 + definitions.length) % definitions.length;
    else if (event.key === "Home") nextIndex = 0;
    else if (event.key === "End") nextIndex = definitions.length - 1;
    else return;
    event.preventDefault();
    setActiveIndex(nextIndex);
    document.getElementById(`project-evaluation-tab-${nextIndex}`)?.focus();
  }

  return (
    <section aria-labelledby="project-questions-heading">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.16em] text-[var(--color-text-muted)]">EVALUATION</p>
          <h2 id="project-questions-heading" className="mt-1 text-lg font-semibold">事業を深める</h2>
        </div>
        <p className="text-xs text-[var(--color-text-muted)]">根拠と未確認を分けて検討</p>
      </div>
      <div role="tablist" aria-label="事業を深める観点" className="flex gap-1 overflow-x-auto border-b border-[var(--color-border-subtle)] pb-px">
        {definitions.map(({ key, label }, index) => (
          <button key={key} data-project-question="true" id={`project-evaluation-tab-${index}`} type="button" role="tab" aria-selected={activeIndex === index} aria-controls={`project-evaluation-panel-${index}`} tabIndex={activeIndex === index ? 0 : -1} onClick={() => setActiveIndex(index)} onKeyDown={(event) => selectFromKeyboard(event, index)} className={`shrink-0 border-b-2 px-3 py-2 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring)] ${activeIndex === index ? "border-[var(--color-primary)] text-[var(--color-text)]" : "border-transparent text-[var(--color-text-muted)] hover:text-[var(--color-text)]"}`}>
            {label}
          </button>
        ))}
      </div>
      <Card id={`project-evaluation-panel-${activeIndex}`} role="tabpanel" aria-labelledby={`project-evaluation-tab-${activeIndex}`} className="mt-4 p-5">
        <div className="flex items-center justify-between gap-3"><h3 className="text-base font-semibold">{activeTab.label}</h3><Badge variant="secondary">{activeSection.status}</Badge></div>
        <p className="mt-3 text-sm leading-6">{activeSection.summary}</p>
        <dl className="mt-5 grid gap-4 border-t border-[var(--color-border-subtle)] pt-4 text-sm leading-6 sm:grid-cols-2">
          <div><dt className="font-semibold text-[var(--color-text-muted)]">根拠</dt><dd className="mt-1">{activeSection.evidence}</dd></div>
          <div><dt className="font-semibold text-[var(--color-text-muted)]">未確認</dt><dd className="mt-1">{activeSection.unknown}</dd></div>
        </dl>
      </Card>
    </section>
  );
}
