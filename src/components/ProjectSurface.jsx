import { useEffect, useMemo, useRef, useState } from "react";
import { Download } from "lucide-react";
import { createProjectConversationRepository } from "./projectConversationRepository";
import { MODEL_CATALOG } from "../models/modelCatalog";
import { Badge } from "./ui/Badge";
import { Button } from "./ui/Button";
import { Card } from "./ui/Card";
import { ProjectComposer } from "./ProjectComposer";
import { ProjectEvaluationTabs } from "./ProjectEvaluationTabs";

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
const downloadFormalPlanDocx = async (project) =>
  (await import("./formalPlanDocxAdapter")).downloadFormalPlanDocx(project);

function createDraftProject() {
  return {
    name: "新しいプロジェクト",
    status: "下書き",
    overview: "Dots. AI との会話から、事業の仮説を少しずつ育てていきます。",
    decisions: [],
    sections: Object.fromEntries(
      evaluationDefinitions.map(({ key }) => [
        key,
        {
          status: "未確認",
          summary:
            "この観点について、まず確かめたいことを言葉にしてみましょう。",
          evidence: "まだ根拠は登録されていません。",
          unknown: "Dots. AI と一緒に確認する問いを決めましょう。",
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

export function ProjectSurface({
  state = "populated",
  project: projectFixture,
  adoptedProject,
  conversationRepository,
  downloadDocx = downloadFormalPlanDocx,
  downloadPdf = downloadFormalPlanPdf,
  models = MODEL_CATALOG,
  initialModelKey = DEFAULT_PROJECT_MODEL_KEY,
  targetView,
  targetEvidence,
  onTargetViewHandled,
}) {
  const [draftStarted, setDraftStarted] = useState(false);
  const [messages, setMessages] = useState([]);
  const [composerDraft, setComposerDraft] = useState("");
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
  const messageRevisionRef = useRef(0);
  const draftRevisionRef = useRef(0);
  const draftPersistQueueRef = useRef(Promise.resolve());

  function updateComposerDraft(value) {
    const revision = ++draftRevisionRef.current;
    setComposerDraft(value);
    draftPersistQueueRef.current = draftPersistQueueRef.current
      .catch(() => undefined)
      .then(() => repository.saveDraft?.(value))
      .catch(() => undefined);
    return revision;
  }

  async function loadConversation(retry = false) {
    const request = ++loadId.current;
    setPhase("loading");
    setConversationError("");
    try {
      const saved = await (retry && repository.retryLoad ? repository.retryLoad() : repository.load());
      if (request !== loadId.current) return;
      if (repository.getLastError?.()) throw repository.getLastError();
      const next = Array.isArray(saved) ? saved : [];
      messagesRef.current = next;
      setMessages(next);
      setPhase("ready");
    } catch {
      if (request !== loadId.current) return;
      setConversationError("会話を読み込めませんでした。保存済みデータは変更していません。");
      setPhase("error");
    }
  }

  useEffect(() => {
    void loadConversation();
    const draftRevision = draftRevisionRef.current;
    void repository.loadDraft?.().then((savedDraft) => {
      if (draftRevision === draftRevisionRef.current && typeof savedDraft === "string") setComposerDraft(savedDraft);
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
    const revision = ++messageRevisionRef.current;
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
        if (
          request !== loadId.current ||
          revision !== messageRevisionRef.current
        )
          return;
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

  async function exportDocx() {
    try {
      await downloadDocx(project);
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
        aria-busy={phase === "loading"}
        className="Dots-composer-layout mx-auto min-h-[calc(100vh-3rem)] w-full max-w-5xl py-4"
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
            <li>1. Dots. AI と仮説を話す</li>
            <li>2. 残したい案をプロジェクトに採用する</li>
            <li>3. 5つの観点から根拠を確かめる</li>
          </ol>
          <p className="mt-3 text-xs text-[var(--color-text-muted)]">
            入力すると一時的な下書きとして始まります。
          </p>
        </Card>
        {phase === "error" && <div role="alert" className="mt-4 flex items-center gap-2 text-sm text-red-700"><span>{conversationError}</span><Button type="button" variant="secondary" onClick={() => void loadConversation(true)}>会話を再試行</Button></div>}
        <ProjectComposer
          disabled={phase !== "ready"}
          loading={phase === "loading"}
          value={composerDraft}
          onValueChange={updateComposerDraft}
          onCompleteDraft={completeProjectDraft}
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
      aria-busy={phase === "loading"}
      className="Dots-composer-layout mx-auto min-h-[calc(100vh-3rem)] w-full max-w-6xl pb-12"
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
              Dots. AI と検討する
            </h2>
            {conversationError && <div role="alert" className="mb-3 flex items-center gap-2 text-sm text-red-700"><span>{conversationError}</span>{phase === "error" && <Button type="button" variant="secondary" onClick={() => void loadConversation(true)}>会話を再試行</Button>}</div>}
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
            <ProjectComposer
              disabled={phase !== "ready"}
              loading={phase === "loading"}
              value={composerDraft}
              onValueChange={updateComposerDraft}
              onCompleteDraft={completeProjectDraft}
              onSubmit={send}
              modelKey={modelKey}
              models={models}
              onModelChange={setModelKey}
            />
          </div>
          <ProjectEvaluationTabs
            definitions={evaluationDefinitions}
            fallbackSections={createDraftProject().sections}
            project={project}
            targetView={targetView}
            targetEvidence={targetEvidence}
            onTargetViewHandled={onTargetViewHandled}
          />
        </div>
      </div>
    </section>
  );
}
