import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowUp, Download, Sparkles } from "lucide-react";
import { createProjectConversationRepository } from "./projectConversationRepository";
import { downloadFormalPlanDocx } from "./formalPlanDocxAdapter";
import { MODEL_CATALOG } from "../models/modelCatalog";
import { Badge } from "./ui/Badge";
import { Button } from "./ui/Button";
import { Card } from "./ui/Card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "./ui/DropdownMenu";

export const projectEvaluationTabs = [
  "どんな事業？",
  "市場はある？",
  "競合は誰？",
  "利益は出る？",
  "実現できる？",
];
const evaluationDefinitions = [
  { key: "どんな事業？", label: "どんな事業？" },
  { key: "市場はある？", label: "市場はある？" },
  { key: "競合は誰？", label: "競合は誰？" },
  // Existing persisted data uses this original spelling. The visible copy is modernized only.
  { key: "利益はでる？", label: "利益は出る？" },
  { key: "実現できる？", label: "実現できる？" },
];
const DEFAULT_PROJECT_MODEL_KEY =
  MODEL_CATALOG.find((model) => model.logicalKey === "gpt-5.6-terra")
    ?.logicalKey ?? MODEL_CATALOG[0]?.logicalKey;
const downloadFormalPlanPdf = async (project) =>
  (await import("./formalPlanPdfAdapter")).downloadFormalPlanPdf(project);

function createDraftProject() {
  return {
    name: "新しいプロジェクト",
    status: "下書き",
    overview: "Kadode AI との会話から、事業の仮説を少しずつ育てていきます。",
    decisions: [],
    sections: Object.fromEntries(
      evaluationDefinitions.map(({ key }) => [
        key,
        {
          status: "未確認",
          summary:
            "この観点について、まず確かめたいことを言葉にしてみましょう。",
          evidence: "まだ根拠は登録されていません。",
          unknown: "Kadode AI と一緒に確認する問いを決めましょう。",
        },
      ]),
    ),
  };
}

export function nextProjectAssistantReply(projectName, message) {
  return `「${projectName}」について、${message.slice(0, 80)} を、顧客・根拠・次に確かめることの順で整理していきましょう。`;
}

export function completeProjectDraft(value) {
  const draft = value.trim();
  return draft
    ? `${draft}。顧客、根拠、次に確かめることもあわせて整理してください。`
    : "顧客、根拠、次に確かめることを分けて整理してください。";
}

function Composer({ disabled, onSubmit, modelKey, models, onModelChange }) {
  const [message, setMessage] = useState("");
  const modelLabel =
    models.find((model) => model.logicalKey === modelKey)?.displayName ??
    "GPT-5.6 Terra";
  const submit = () => {
    const next = message.trim();
    if (!next || disabled) return;
    onSubmit(next);
    setMessage("");
  };

  return (
    <form
      className="kadode-composer kadode-composer--anchored"
      aria-label="Project Kadode AI composer"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <label htmlFor="project-composer" className="sr-only">
        このプロジェクトについて Kadode AI に尋ねる
      </label>
      <textarea
        id="project-composer"
        disabled={disabled}
        className="kadode-composer__textarea kadode-composer__textarea--compact resize-none placeholder:text-[var(--color-text-muted)] disabled:cursor-wait"
        value={message}
        onChange={(event) => setMessage(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            submit();
          }
        }}
        placeholder={
          disabled
            ? "会話を読み込んでいます…"
            : "検討したい事業案を簡単に教えてください"
        }
      />
      <div className="kadode-composer__actions">
        <Button
          type="button"
          variant="ghost"
          onClick={() => setMessage((value) => completeProjectDraft(value))}
          className="min-h-9 gap-1 px-2 text-xs"
          disabled={disabled}
        >
          <Sparkles className="size-4" aria-hidden="true" />
          AIで補完
        </Button>
        <div className="flex items-center gap-1">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                className="min-h-9 px-2 text-xs"
                disabled={disabled}
                aria-label={`モデル: ${modelLabel}`}
              >
                {modelLabel}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" aria-label="AIモデルを選ぶ">
              <DropdownMenuLabel>AIモデル</DropdownMenuLabel>
              {models.map((model) => (
                <DropdownMenuItem
                  key={model.logicalKey}
                  onSelect={() => onModelChange(model.logicalKey)}
                >
                  {model.displayName}
                  {model.logicalKey === modelKey ? " ✓" : ""}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
          <Button
            type="submit"
            disabled={disabled || !message.trim()}
            className="min-h-9 rounded-lg px-3"
            aria-label="送信"
          >
            <ArrowUp className="size-4" />
          </Button>
        </div>
      </div>
    </form>
  );
}

function EvaluationTabs({ project }) {
  const [activeIndex, setActiveIndex] = useState(0);
  const activeTab = evaluationDefinitions[activeIndex];
  const activeLabel = activeTab.label;
  const fallbackSections = createDraftProject().sections;
  const activeSection =
    project.sections?.[activeTab.key] ??
    project.sections?.[activeTab.label] ??
    fallbackSections[activeTab.key];

  function selectFromKeyboard(event, index) {
    let nextIndex = index;
    if (event.key === "ArrowRight")
      nextIndex = (index + 1) % evaluationDefinitions.length;
    else if (event.key === "ArrowLeft")
      nextIndex =
        (index - 1 + evaluationDefinitions.length) %
        evaluationDefinitions.length;
    else if (event.key === "Home") nextIndex = 0;
    else if (event.key === "End") nextIndex = evaluationDefinitions.length - 1;
    else return;
    event.preventDefault();
    setActiveIndex(nextIndex);
    document.getElementById(`project-evaluation-tab-${nextIndex}`)?.focus();
  }

  return (
    <section aria-labelledby="project-questions-heading">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.16em] text-[var(--color-text-muted)]">
            EVALUATION
          </p>
          <h2
            id="project-questions-heading"
            className="mt-1 text-lg font-semibold"
          >
            事業を深める
          </h2>
        </div>
        <p className="text-xs text-[var(--color-text-muted)]">
          根拠と未確認を分けて検討
        </p>
      </div>
      <div
        role="tablist"
        aria-label="事業を深める観点"
        className="flex gap-1 overflow-x-auto border-b border-[var(--color-border-subtle)] pb-px"
      >
        {evaluationDefinitions.map(({ key, label }, index) => (
          <button
            key={key}
            data-project-question="true"
            id={`project-evaluation-tab-${index}`}
            type="button"
            role="tab"
            aria-selected={activeIndex === index}
            aria-controls={`project-evaluation-panel-${index}`}
            tabIndex={activeIndex === index ? 0 : -1}
            onClick={() => setActiveIndex(index)}
            onKeyDown={(event) => selectFromKeyboard(event, index)}
            className={`shrink-0 border-b-2 px-3 py-2 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring)] ${activeIndex === index ? "border-[var(--color-primary)] text-[var(--color-text)]" : "border-transparent text-[var(--color-text-muted)] hover:text-[var(--color-text)]"}`}
          >
            {label}
          </button>
        ))}
      </div>
      <Card
        id={`project-evaluation-panel-${activeIndex}`}
        role="tabpanel"
        aria-labelledby={`project-evaluation-tab-${activeIndex}`}
        className="mt-4 p-5"
      >
        <div className="flex items-center justify-between gap-3">
          <h3 className="text-base font-semibold">{activeLabel}</h3>
          <Badge variant="secondary">{activeSection.status}</Badge>
        </div>
        <p className="mt-3 text-sm leading-6">{activeSection.summary}</p>
        <dl className="mt-5 grid gap-4 border-t border-[var(--color-border-subtle)] pt-4 text-sm leading-6 sm:grid-cols-2">
          <div>
            <dt className="font-semibold text-[var(--color-text-muted)]">
              根拠
            </dt>
            <dd className="mt-1">{activeSection.evidence}</dd>
          </div>
          <div>
            <dt className="font-semibold text-[var(--color-text-muted)]">
              未確認
            </dt>
            <dd className="mt-1">{activeSection.unknown}</dd>
          </div>
        </dl>
      </Card>
    </section>
  );
}

export function ProjectSurface({
  state = "populated",
  project: projectFixture,
  adoptedProject,
  conversationRepository,
  downloadDocx = downloadFormalPlanDocx,
  downloadPdf = downloadFormalPlanPdf,
  models = MODEL_CATALOG,
  initialModelKey = DEFAULT_PROJECT_MODEL_KEY,
}) {
  const [draftStarted, setDraftStarted] = useState(false);
  const [messages, setMessages] = useState([]);
  const [phase, setPhase] = useState("loading");
  const [conversationError, setConversationError] = useState("");
  const [exportStatus, setExportStatus] = useState("idle");
  const [modelKey, setModelKey] = useState(() =>
    models.some((model) => model.logicalKey === initialModelKey)
      ? initialModelKey
      : models[0]?.logicalKey,
  );
  const hasProject = Boolean(adoptedProject || projectFixture || draftStarted);
  const project = adoptedProject
    ? {
        name: adoptedProject.title,
        status: adoptedProject.status,
        overview: adoptedProject.inference,
        decisions: adoptedProject.reason
          ? [
              {
                id: `${adoptedProject.id}-adoption`,
                kind: "採用",
                date: "",
                title: adoptedProject.title,
                reason: adoptedProject.reason,
              },
            ]
          : [],
        sections: Object.fromEntries(
          evaluationDefinitions.map(({ key }) => [
            key,
            {
              status: "未確認",
              summary: "この観点はProjectで検討します。",
              evidence: adoptedProject.fact,
              unknown: "Projectでの会話から仮説を更新します。",
            },
          ]),
        ),
      }
    : (projectFixture ?? createDraftProject());
  const projectId =
    adoptedProject?.id ?? projectFixture?.datasetId ?? "new-project";
  const ownerId = adoptedProject?.ownerId ?? "local-owner";
  const spaceId = adoptedProject?.spaceId ?? "local-space";
  const browserRepository = useMemo(
    () => createProjectConversationRepository({ ownerId, spaceId, projectId }),
    [ownerId, projectId, spaceId],
  );
  const repository = conversationRepository ?? browserRepository;
  const loadId = useRef(0);
  const messagesRef = useRef([]);
  const persistQueueRef = useRef(Promise.resolve());
  const messageSequenceRef = useRef(0);

  useEffect(() => {
    const request = ++loadId.current;
    setPhase("loading");
    setConversationError("");
    Promise.resolve(repository.load())
      .then((saved) => {
        if (request !== loadId.current) return;
        const next = Array.isArray(saved) ? saved : [];
        messagesRef.current = next;
        setMessages(next);
        setPhase("ready");
      })
      .catch(() => {
        if (request !== loadId.current) return;
        setConversationError(
          "会話を読み込めませんでした。ページを再読み込みしてください。",
        );
        setPhase("error");
      });
    return () => {
      loadId.current += 1;
    };
  }, [repository]);

  async function send(message) {
    if (phase !== "ready") return;
    if (!hasProject) setDraftStarted(true);
    const request = loadId.current;
    const now = Date.now();
    const sequence = ++messageSequenceRef.current;
    const next = [
      ...messagesRef.current,
      { id: `user-${now}-${sequence}`, role: "user", content: message },
      {
        id: `assistant-${now}-${sequence}`,
        role: "assistant",
        content: nextProjectAssistantReply(project.name, message),
      },
    ];
    messagesRef.current = next;
    setMessages(next);
    persistQueueRef.current = persistQueueRef.current
      .catch(() => undefined)
      .then(async () => {
        const saved = await repository.save(next);
        if (request !== loadId.current) return;
        messagesRef.current = saved;
        setMessages(saved);
        setConversationError("");
      })
      .catch(() => {
        if (request === loadId.current)
          setConversationError(
            "会話を保存できませんでした。もう一度お試しください。",
          );
      });
  }

  function exportDocx() {
    try {
      downloadDocx(project);
      setExportStatus("downloaded");
    } catch {
      setExportStatus("error");
    }
  }

  async function exportPdf() {
    try {
      await downloadPdf(project);
      setExportStatus("pdf-downloaded");
    } catch {
      setExportStatus("pdf-error");
    }
  }

  if (!hasProject)
    return (
      <section
        aria-labelledby="project-surface-heading"
        className="kadode-composer-layout mx-auto min-h-[calc(100vh-3rem)] w-full max-w-5xl py-4"
      >
        <p className="text-xs font-bold uppercase tracking-[0.16em] text-[var(--color-text-muted)]">
          PROJECT
        </p>
        <h1
          id="project-surface-heading"
          className="mt-1 text-xl font-semibold tracking-tight"
        >
          Projectをはじめる
        </h1>
        <Card className="mt-6 max-w-2xl p-6">
          <h2 className="text-base font-semibold">
            話したアイデアを、ひとつのプロジェクトに育てましょう
          </h2>
          <ol className="mt-4 space-y-2 text-sm leading-6 text-[var(--color-text-muted)]">
            <li>1. Kadode AI と仮説を話す</li>
            <li>2. 残したい案をプロジェクトに採用する</li>
            <li>3. 5つの観点から根拠を確かめる</li>
          </ol>
          <p className="mt-3 text-xs text-[var(--color-text-muted)]">
            入力すると一時的な下書きとして始まります。
          </p>
        </Card>
        <Composer
          disabled={phase !== "ready"}
          onSubmit={send}
          modelKey={modelKey}
          models={models}
          onModelChange={setModelKey}
        />
      </section>
    );

  const status = {
    loading: "読み込み中",
    error: "確認が必要",
    empty: "検討中",
    populated: project.status,
  }[state];
  return (
    <section
      aria-labelledby="project-surface-heading"
      className="kadode-composer-layout mx-auto min-h-[calc(100vh-3rem)] w-full max-w-6xl pb-12"
    >
      <header className="flex flex-wrap items-start justify-between gap-4 border-b border-[var(--color-border-subtle)] pb-5">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.16em] text-[var(--color-text-muted)]">
            PROJECT
          </p>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <h1
              id="project-surface-heading"
              className="text-xl font-semibold tracking-tight"
            >
              {project.name}
            </h1>
            <Badge variant="outline">{status}</Badge>
          </div>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-[var(--color-text-muted)]">
            {project.overview}
          </p>
        </div>
        <Button
          type="button"
          variant="ghost"
          className="min-h-9 gap-1 px-2 text-xs text-[var(--color-text-muted)]"
          onClick={exportDocx}
        >
          <Download className="size-4" />
          DOCXをダウンロード
        </Button>
        <Button
          type="button"
          variant="ghost"
          className="min-h-9 gap-1 px-2 text-xs text-[var(--color-text-muted)]"
          onClick={exportPdf}
        >
          <Download className="size-4" />
          PDFをダウンロード
        </Button>
      </header>
      {exportStatus === "downloaded" && (
        <p
          className="mt-3 text-sm text-[var(--color-text-muted)]"
          role="status"
        >
          編集できるDOCXをダウンロードしました。
        </p>
      )}
      {exportStatus === "pdf-downloaded" && (
        <p className="mt-3 text-sm text-[var(--color-text-muted)]" role="status">
          提出用のPDF下書きをダウンロードしました。
        </p>
      )}
      {exportStatus === "error" && (
        <p className="mt-3 text-sm text-red-700" role="alert">
          DOCXを作成できませんでした。もう一度お試しください。
        </p>
      )}
      {exportStatus === "pdf-error" && (
        <p className="mt-3 text-sm text-red-700" role="alert">
          PDFを作成できませんでした。もう一度お試しください。
        </p>
      )}
      <div className="mt-7 grid gap-8 lg:grid-cols-[minmax(0,1.3fr)_minmax(19rem,.7fr)]">
        <div className="min-w-0 space-y-7">
          <div>
            <h2 className="mb-3 text-base font-semibold">
              Kadode AI と検討する
            </h2>
            {conversationError && (
              <p role="alert" className="mb-3 text-sm text-red-700">
                {conversationError}
              </p>
            )}
            {messages.length > 0 && (
              <ol className="mb-4 space-y-3" aria-label="Project conversation">
                {messages.map((message) => (
                  <li
                    key={message.id}
                    data-message-role={message.role}
                    className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-6 ${message.role === "user" ? "ml-auto bg-[var(--color-muted)]" : "bg-[var(--color-surface-raised)] ring-1 ring-[var(--color-border-subtle)]"}`}
                  >
                    {message.content}
                  </li>
                ))}
              </ol>
            )}
            <Composer
              disabled={phase !== "ready"}
              onSubmit={send}
              modelKey={modelKey}
              models={models}
              onModelChange={setModelKey}
            />
          </div>
          <EvaluationTabs project={project} />
        </div>
      </div>
    </section>
  );
}
