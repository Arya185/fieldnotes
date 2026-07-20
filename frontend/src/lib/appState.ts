import type { RefObject } from "react";
import { useEffect, useState } from "react";

import { fetchArtifact } from "./api";
import { useAskState } from "./appState/askState";
import type { ContextTab, RouteKey } from "./appState/types";
import { getInitialRoute, routes, formatDateTime, formatRelative, copyText } from "./appState/utils";
import { useQuizState } from "./appState/quizState";
import { useWorkspaceState } from "./appState/workspaceState";

export type {
  ArtifactPreview,
  ChatMessage,
  ContextTab,
  NoteOverrides,
  QuizReviewItem,
  QuizState,
  RouteKey,
  SourceAccordionState,
  SourceNavItem,
  SourceViewState,
} from "./appState/types";
export { formatDateTime, formatRelative } from "./appState/utils";

export function useFieldnotesApp(composerRef: RefObject<HTMLTextAreaElement | null>) {
  const [route, setRoute] = useState<RouteKey>(getInitialRoute);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [contextPanelOpen, setContextPanelOpen] = useState(false);
  const [contextTab, setContextTab] = useState<ContextTab>("sources");
  const [busy, setBusy] = useState(false);
  const [statusMessage, setStatusMessage] = useState("Ready.");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const workspace = useWorkspaceState({
    setBusy,
    setErrorMessage,
    setStatusMessage,
    setContextTab,
    setContextPanelOpen,
    setRoute,
  });

  const ask = useAskState({
    activeWorkspaceId: workspace.activeWorkspaceId,
    route,
    composerRef,
    loadNotebookForWorkspace: workspace.loadNotebookForWorkspace,
    handleJumpToSource: workspace.handleJumpToSource,
    setBusy,
    setErrorMessage,
    setStatusMessage,
    setContextTab,
    setContextPanelOpen,
  });

  const quiz = useQuizState({
    activeWorkspaceId: workspace.activeWorkspaceId,
    chatMessages: ask.chatMessages,
    loadNotebookForWorkspace: workspace.loadNotebookForWorkspace,
    setBusy,
    setErrorMessage,
    setStatusMessage,
  });

  useEffect(() => {
    window.location.hash = route;
  }, [route]);

  useEffect(() => {
    if (route === "notebook") {
      setContextTab("notebook");
      setContextPanelOpen(true);
    }
    if (route === "quiz") {
      setContextTab("quiz");
      setContextPanelOpen(true);
    }
    if (route === "source") {
      setContextTab("sources");
      setContextPanelOpen(true);
    }
  }, [route]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        composerRef.current?.focus();
      }
      if (event.key === "Escape" && ask.streamingAnswerId) {
        event.preventDefault();
        ask.handleCancelResponse();
      }
      if ((event.metaKey || event.ctrlKey) && event.shiftKey && event.key.toLowerCase() === "r") {
        event.preventDefault();
        void ask.handleRetryLast();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [ask, composerRef]);

  const visibleRoutes = routes.filter((item) => workspace.developerMode || item !== "developer");

  const currentTitle =
    route === "chat"
      ? "Ask your workspace"
      : route === "notebook"
        ? "Notebook"
        : route === "quiz"
          ? "Study mode"
          : route === "source"
            ? "Source viewer"
            : route === "developer"
              ? "Developer diagnostics"
              : "Workspace overview";

  async function exportArtifact(card: { id: string }) {
    if (!workspace.activeWorkspaceId) {
      return;
    }
    try {
      const response = await fetchArtifact(workspace.activeWorkspaceId, card.id);
      const text = await response.text();
      await copyText(text);
      setStatusMessage("Artifact markdown copied.");
    } catch (error) {
      setErrorMessage(`Artifact export failed: ${(error as Error).message}`);
    }
  }

  async function copySourceRef() {
    if (!workspace.sourceView.response) {
      return;
    }
    await copyText(`${workspace.sourceView.response.file_path} -> ${workspace.sourceView.response.label} -> ${workspace.sourceView.locator ?? ""}`);
    setStatusMessage("Source reference copied.");
  }

  function clearActiveWorkspace() {
    workspace.clearActiveWorkspace();
    ask.setChatMessages([]);
  }

  async function handleSourceNav(direction: -1 | 1) {
    if (workspace.sourceView.citationIndex === undefined) {
      return;
    }
    const nextIndex = workspace.sourceView.citationIndex + direction;
    const next = ask.allCitations[nextIndex];
    if (next?.anchor) {
      await workspace.handleJumpToSource(next.anchor, nextIndex);
    }
  }

  return {
    route,
    setRoute,
    visibleRoutes,
    currentTitle,
    sidebarCollapsed,
    setSidebarCollapsed,
    contextPanelOpen,
    setContextPanelOpen,
    contextTab,
    setContextTab,
    busy,
    statusMessage,
    errorMessage,
    recentWorkspaces: workspace.recentWorkspaces,
    indexHistory: workspace.indexHistory,
    developerMode: workspace.developerMode,
    setDeveloperMode: workspace.setDeveloperMode,
    folderPath: workspace.folderPath,
    setFolderPath: workspace.setFolderPath,
    activeWorkspaceId: workspace.activeWorkspaceId,
    setActiveWorkspaceId: workspace.setActiveWorkspaceId,
    activeWorkspace: workspace.activeWorkspace,
    chatInput: ask.chatInput,
    setChatInput: ask.setChatInput,
    chatMessages: ask.chatMessages,
    starterSummary: workspace.starterSummary,
    indexEvents: workspace.indexEvents,
    notebook: workspace.notebook,
    artifactFilter: workspace.artifactFilter,
    setArtifactFilter: workspace.setArtifactFilter,
    artifactSearch: workspace.artifactSearch,
    setArtifactSearch: workspace.setArtifactSearch,
    artifactSort: workspace.artifactSort,
    setArtifactSort: workspace.setArtifactSort,
    artifactPreview: workspace.artifactPreview,
    pinnedArtifacts: workspace.pinnedArtifacts,
    noteOverrides: workspace.noteOverrides,
    quizState: quiz.quizState,
    incorrectReviewOnly: quiz.incorrectReviewOnly,
    setIncorrectReviewOnly: quiz.setIncorrectReviewOnly,
    sourceView: workspace.sourceView,
    developerSummary: workspace.developerSummary,
    developerChunks: ask.developerChunks,
    typingIndicator: ask.typingIndicator,
    dragActive: workspace.dragActive,
    setDragActive: workspace.setDragActive,
    runtimeMode: workspace.runtimeMode,
    sourceSearch: workspace.sourceSearch,
    setSourceSearch: workspace.setSourceSearch,
    sourcePanelExpanded: workspace.sourcePanelExpanded,
    setSourcePanelExpanded: workspace.setSourcePanelExpanded,
    allSourcesExpanded: ask.allSourcesExpanded,
    setAllSourcesExpanded: ask.setAllSourcesExpanded,
    sourceAccordionState: ask.sourceAccordionState,
    setSourceAccordionState: ask.setSourceAccordionState,
    chatScrollRef: ask.chatScrollRef,
    indexedDocumentCount: workspace.indexedDocumentCount,
    lastIndexEntry: workspace.lastIndexEntry,
    filteredArtifacts: workspace.filteredArtifacts,
    sourceSearchResults: workspace.sourceSearchResults,
    conceptSummary: quiz.conceptSummary,
    reviewItems: quiz.reviewItems,
    indexedPages: workspace.indexedPages,
    fileTypeSummary: workspace.fileTypeSummary,
    noBackend: Boolean(workspace.noBackend),
    allCitations: ask.allCitations,
    sourceNavItems: ask.sourceNavItems,
    handleIndex: workspace.handleIndex,
    requestAnswer: ask.requestAnswer,
    handleCancelResponse: ask.handleCancelResponse,
    handleRetryLast: ask.handleRetryLast,
    handleRegenerate: ask.handleRegenerate,
    handleOpenArtifact: workspace.handleOpenArtifact,
    handleStartQuiz: quiz.handleStartQuiz,
    handleAnswerQuiz: quiz.handleAnswerQuiz,
    handleJumpToSource: ask.openCitation,
    handleSourceNav,
    handleBenchmarkImport: workspace.handleBenchmarkImport,
    handleDropWorkspace: workspace.handleDropWorkspace,
    exportConversation: ask.exportConversation,
    exportArtifact,
    copyCitation: ask.copyCitation,
    copyAnswer: ask.copyAnswer,
    copySourceRef,
    renameArtifact: workspace.renameArtifact,
    deleteArtifact: workspace.deleteArtifact,
    clearActiveWorkspace,
    loadNotebookForWorkspace: workspace.loadNotebookForWorkspace,
    setPinnedArtifacts: workspace.setPinnedArtifacts,
    onChatScroll: ask.onChatScroll,
    formatDateTime,
    formatRelative,
  };
}
