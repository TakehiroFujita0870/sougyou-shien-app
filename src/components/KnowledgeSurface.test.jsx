// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import fixture from "../fixtures/knowledge-admin-demo.json";
import { KnowledgeSurface } from "./KnowledgeSurface";
import { createKnowledgeConversationRepository } from "./knowledgeConversationRepository";
import { createKnowledgeMetadataRepository } from "./knowledgeMetadataRepository";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const memoryStorage = () => {
  const values = new Map();
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
  };
};
async function mount(props = {}) {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  await act(async () =>
    root.render(
      <KnowledgeSurface
        fixture={fixture}
        repository={createKnowledgeMetadataRepository({
          ownerId: "a",
          spaceId: "s",
          storage: memoryStorage(),
        })}
        conversationRepository={createKnowledgeConversationRepository({
          ownerId: "a",
          spaceId: "s",
          storage: memoryStorage(),
        })}
        {...props}
      />,
    ),
  );
  return {
    container,
    unmount: () =>
      act(() => {
        root.unmount();
        container.remove();
      }),
  };
}

describe("KnowledgeSurface library", () => {
  it("opens only a resolvable same-owner Project evidence target", async () => {
    const onOpenProject = vi.fn();
    const project = { id: 'project-a', ownerId: 'local-owner', spaceId: 'local-space' };
    const conversationRepository = { load: async () => ({ messages: [], entries: [{ id: 'evidence', category: 'decision', title: '採用判断', content: '根拠', createdAt: '2026-08-11T00:00:00.000Z', updatedAt: '2026-08-11T00:00:00.000Z', sourceType: 'local', confidence: 'unknown', unknowns: [], projectId: 'project-a', evaluationView: '市場はある？' }] }), save: async (value) => value };
    const { container, unmount } = await mount({ ownerId: 'local-owner', spaceId: 'local-space', availableProjects: [project], allowedEvaluationViews: ['市場はある？'], conversationRepository, onOpenProject });
    await act(async () => Promise.resolve());
    const button = [...container.querySelectorAll('button')].find((item) => item.textContent === 'Projectを開く');
    expect(button).toBeTruthy();
    await act(async () => button.click());
    expect(onOpenProject).toHaveBeenCalledWith('project-a', '市場はある？');
    await unmount();
  });
  it("shows a compact searchable, category-filterable library without network calls", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const { container, unmount } = await mount();
    await act(async () => Promise.resolve());
    expect(container.textContent).toContain("ナレッジライブラリ");
    expect(container.textContent).toContain("顧客ヒアリング要約");
    expect(container.textContent).toContain("小規模な検証から始める");
    const search = container.querySelector(
      'input[placeholder="タイトル・本文を検索"]',
    );
    await act(async () => {
      search.value = "顧客";
      search.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(container.textContent).toContain("顧客ヒアリング要約");
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
    await unmount();
  });
  it("previews deterministic classification and saves only after confirmation, surviving reload", async () => {
    const store = memoryStorage();
    const conversationRepository = createKnowledgeConversationRepository({
      ownerId: "a",
      spaceId: "s",
      storage: store,
    });
    const props = {
      conversationRepository,
      repository: createKnowledgeMetadataRepository({
        ownerId: "a",
        spaceId: "s",
        storage: store,
      }),
    };
    const first = await mount(props);
    const input = first.container.querySelector("#knowledge-composer");
    const setter = Object.getOwnPropertyDescriptor(
      HTMLTextAreaElement.prototype,
      "value",
    ).set;
    await act(async () => {
      setter.call(input, "採用する市場調査の進め方");
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(
        new KeyboardEvent("keydown", {
          key: "Enter",
          bubbles: true,
          cancelable: true,
        }),
      );
    });
    expect((await conversationRepository.load()).entries).toHaveLength(0);
    expect(document.querySelector('[role="dialog"]')).toBeTruthy();
    await act(async () =>
      [...document.querySelectorAll("button")]
        .find((button) => button.textContent === "ナレッジに追加")
        .click(),
    );
    expect((await conversationRepository.load()).entries[0]).toMatchObject({
      category: "decision",
      projectId: "",
      evaluationView: "",
    });
    await first.unmount();
    const second = await mount({
      ...props,
      conversationRepository: createKnowledgeConversationRepository({
        ownerId: "a",
        spaceId: "s",
        storage: store,
      }),
    });
    await act(async () => Promise.resolve());
    expect(second.container.textContent).toContain("採用する市場調査");
    await second.unmount();
  });
  it("persists an explicitly selected Project view only for a same-owner current decision", async () => {
    const store = memoryStorage();
    const conversationRepository = createKnowledgeConversationRepository({ ownerId: "local-owner", spaceId: "local-space", storage: store });
    const project = { id: "project-a", ownerId: "local-owner", spaceId: "local-space" };
    const { container, unmount } = await mount({
      ownerId: "local-owner", spaceId: "local-space", conversationRepository, currentProject: project, availableProjects: [project], allowedEvaluationViews: ["市場はある？", "競合は誰？"],
    });
    await act(async () => Promise.resolve());
    const input = container.querySelector("#knowledge-composer");
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set;
    await act(async () => {
      setter.call(input, "採用判断: 顧客ヒアリングを始める");
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
    });
    const view = [...document.querySelectorAll("button")].find((button) => button.textContent === "市場はある？");
    expect(view).toBeTruthy();
    await act(async () => view.click());
    await act(async () => [...document.querySelectorAll("button")].find((button) => button.textContent === "ナレッジに追加").click());
    await vi.waitFor(async () => expect((await conversationRepository.load()).entries[0]).toMatchObject({ projectId: "project-a", evaluationView: "市場はある？", sourceType: "local", confidence: "unknown" }));
    await unmount();
  });
  it("cancels a preview without persistence and has no AI assist widget", async () => {
    const repository = createKnowledgeConversationRepository({
      ownerId: "a",
      spaceId: "s",
      storage: memoryStorage(),
    });
    const { container, unmount } = await mount({
      conversationRepository: repository,
    });
    const input = container.querySelector("#knowledge-composer");
    const setter = Object.getOwnPropertyDescriptor(
      HTMLTextAreaElement.prototype,
      "value",
    ).set;
    await act(async () => {
      setter.call(input, "メモ");
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(
        new KeyboardEvent("keydown", {
          key: "Enter",
          bubbles: true,
          cancelable: true,
        }),
      );
    });
    await act(async () =>
      [...document.querySelectorAll("button")]
        .find((button) => button.textContent === "キャンセル")
        .click(),
    );
    expect((await repository.load()).entries).toEqual([]);
    expect(
      container.querySelector('[data-testid="knowledge-assist"]'),
    ).toBeNull();
    await unmount();
  });
  it("keeps the composer disabled until a deferred initial hydration resolves", async () => {
    let resolveLoad;
    const pending = new Promise((resolve) => {
      resolveLoad = resolve;
    });
    const conversationRepository = {
      load: () => pending,
      save: vi.fn(async (value) => value),
    };
    const { container, unmount } = await mount({ conversationRepository });
    const input = container.querySelector("#knowledge-composer");
    expect(input.disabled).toBe(true);
    await act(async () => resolveLoad({ messages: [], entries: [] }));
    expect(input.disabled).toBe(false);
    const setter = Object.getOwnPropertyDescriptor(
      HTMLTextAreaElement.prototype,
      "value",
    ).set;
    await act(async () => {
      setter.call(input, "採用する検証計画");
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(
        new KeyboardEvent("keydown", {
          key: "Enter",
          bubbles: true,
          cancelable: true,
        }),
      );
    });
    await act(async () =>
      [...document.querySelectorAll("button")]
        .find((button) => button.textContent === "ナレッジに追加")
        .click(),
    );
    expect(container.textContent).toContain("採用する検証計画");
    expect(conversationRepository.save).toHaveBeenCalledWith(
      expect.objectContaining({
        entries: [expect.objectContaining({ content: "採用する検証計画" })],
      }),
    );
    await unmount();
  });
  it("keeps the add confirmation open with a retryable alert after a rejected save", async () => {
    let resolveLoad;
    const pendingLoad = new Promise((resolve) => {
      resolveLoad = resolve;
    });
    const conversationRepository = {
      load: () => pendingLoad,
      save: vi.fn(async () => {
        throw new Error("offline");
      }),
    };
    const { container, unmount } = await mount({ conversationRepository });
    await act(async () => resolveLoad({ messages: [], entries: [] }));
    const input = container.querySelector("#knowledge-composer");
    const setter = Object.getOwnPropertyDescriptor(
      HTMLTextAreaElement.prototype,
      "value",
    ).set;
    await act(async () => {
      setter.call(input, "保存失敗後も確認を残す");
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(
        new KeyboardEvent("keydown", {
          key: "Enter",
          bubbles: true,
          cancelable: true,
        }),
      );
    });
    const dialog = document.querySelector('[role="dialog"]');
    const confirm = [...dialog.querySelectorAll("button")].find(
      (button) => button.textContent === "ナレッジに追加",
    );
    await act(async () => {
      confirm.click();
      await Promise.resolve();
    });
    expect(conversationRepository.save).toHaveBeenCalledTimes(1);
    expect(document.querySelector('[role="dialog"]')).toBeTruthy();
    expect(document.querySelector('[role="alert"]').textContent).toContain(
      "ナレッジを保存できませんでした",
    );
    expect(document.querySelector('[role="dialog"]').textContent).toContain(
      "保存失敗後も確認を残す",
    );
    await act(async () => {
      confirm.click();
      await Promise.resolve();
    });
    expect(conversationRepository.save).toHaveBeenCalledTimes(2);
    await unmount();
  });
  it("disables duplicate confirmation while saving and only commits once", async () => {
    let resolveSave;
    const pendingSave = new Promise((resolve) => {
      resolveSave = resolve;
    });
    const conversationRepository = {
      load: async () => ({ messages: [], entries: [] }),
      save: vi.fn(() => pendingSave),
    };
    const { container, unmount } = await mount({ conversationRepository });
    const input = container.querySelector("#knowledge-composer");
    const setter = Object.getOwnPropertyDescriptor(
      HTMLTextAreaElement.prototype,
      "value",
    ).set;
    await act(async () => {
      setter.call(input, "重複保存を防ぐ");
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(
        new KeyboardEvent("keydown", {
          key: "Enter",
          bubbles: true,
          cancelable: true,
        }),
      );
    });
    const dialog = document.querySelector('[role="dialog"]');
    const confirm = [...dialog.querySelectorAll("button")].find(
      (button) => button.textContent === "ナレッジに追加",
    );
    await act(async () => {
      confirm.click();
      await Promise.resolve();
    });
    expect(conversationRepository.save).toHaveBeenCalledTimes(1);
    expect(
      [...dialog.querySelectorAll("button")].find(
        (button) => button.textContent === "保存中…",
      ).disabled,
    ).toBe(true);
    await act(async () => resolveSave({ messages: [], entries: [] }));
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    expect(conversationRepository.save).toHaveBeenCalledTimes(1);
    await unmount();
  });
  it("keeps the delete confirmation and document intact after a rejected delete", async () => {
    let rejectDelete;
    const pendingDelete = new Promise((_, reject) => {
      rejectDelete = reject;
    });
    const documentRecord = {
      id: "local-file:failure.pdf",
      name: "failure.pdf",
      state: "metadata_only",
      mediaType: "pdf",
      sizeBytes: 1024,
      lastModified: 1,
    };
    const repository = {
      load: async () => {},
      list: () => [documentRecord],
      delete: vi.fn(() => pendingDelete),
    };
    const { container, unmount } = await mount({ repository });
    await act(async () => Promise.resolve());
    await act(async () =>
      [...container.querySelectorAll("button")]
        .find((button) => button.textContent === "削除")
        .click(),
    );
    const confirm = [...document.querySelectorAll("button")].find(
      (button) => button.textContent === "削除を確定",
    );
    await act(async () => {
      confirm.click();
      await Promise.resolve();
    });
    expect(repository.delete).toHaveBeenCalledTimes(1);
    await act(async () => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
      rejectDelete(new Error("offline"));
      await Promise.resolve();
    });
    expect(document.querySelector('[role="dialog"]')).toBeTruthy();
    expect(document.querySelector('[role="alert"]').textContent).toContain(
      "ファイルを削除できませんでした",
    );
    expect(container.textContent).toContain("failure.pdf");
    await unmount();
  });

  it("keeps successful metadata visible and preserves the draft across repeated conversation retries", async () => {
    let resolveRetry;
    const retry = new Promise((resolve) => { resolveRetry = resolve; });
    const documentRecord = { id: "local-file:loaded.pdf", name: "loaded.pdf", state: "metadata_only", mediaType: "pdf", sizeBytes: 10, lastModified: 1 };
    const repository = { load: async () => [documentRecord], list: () => [documentRecord], getLastError: () => null };
    const conversationRepository = {
      load: vi.fn(async () => { throw new Error("offline"); }),
      retryLoad: vi.fn().mockRejectedValueOnce(new Error("still offline")).mockImplementationOnce(() => retry),
      save: vi.fn(async (value) => value),
      getLastError: () => null,
    };
    const { container, unmount } = await mount({ repository, conversationRepository });
    await act(async () => Promise.resolve());
    expect(container.textContent).toContain("loaded.pdf");
    expect(container.querySelector('[role="alert"]').textContent).toContain("会話とナレッジを読み込めませんでした");
    const input = container.querySelector("#knowledge-composer");
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set;
    await act(async () => { setter.call(input, "再試行しても残す下書き"); input.dispatchEvent(new Event("input", { bubbles: true })); });
    const retryButton = () => [...container.querySelectorAll("button")].find((button) => button.textContent === "会話履歴を再試行");
    await act(async () => { retryButton().click(); await Promise.resolve(); });
    expect(input.value).toBe("再試行しても残す下書き");
    expect(retryButton()).toBeTruthy();
    await act(async () => { retryButton().click(); await Promise.resolve(); });
    expect(input.disabled).toBe(true);
    expect(input.value).toBe("再試行しても残す下書き");
    await act(async () => resolveRetry({ messages: [{ role: "user", content: "復元済み", createdAt: null }], entries: [] }));
    expect(input.disabled).toBe(false);
    expect(input.value).toBe("再試行しても残す下書き");
    expect(container.textContent).toContain("復元済み");
    expect(container.textContent).toContain("loaded.pdf");
    await unmount();
  });
});
