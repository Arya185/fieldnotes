import { useRef } from "react";

import { Composer } from "./components/Composer";
import {
  useFieldnotesApp,
} from "./lib/appState";
import { AppSidebar } from "./routes/AppSidebar";
import { ChatRoute } from "./routes/ChatRoute";
import { ContextPanelRoute } from "./routes/ContextPanelRoute";
import { DeveloperRoute } from "./routes/DeveloperRoute";
import { NotebookRoute } from "./routes/NotebookRoute";
import { QuizRoute } from "./routes/QuizRoute";
import { SourceRoute } from "./routes/SourceRoute";
import { WorkspaceRoute } from "./routes/WorkspaceRoute";
import "./styles.css";

export default function App() {
  const composerRef = useRef<HTMLTextAreaElement | null>(null);
  const app = useFieldnotesApp(composerRef);

  return (
    <div
      className={`app-shell ${app.developerMode ? "dev-on" : ""} ${app.dragActive ? "drag-on" : ""} ${
        app.sidebarCollapsed ? "sidebar-collapsed" : ""
      } ${app.contextPanelOpen ? "context-open" : "context-closed"}`}
    >
      <div className="sr-only" aria-live="polite">
        {app.typingIndicator ? "Assistant typing." : app.statusMessage}
      </div>

      <AppSidebar
        sidebarCollapsed={app.sidebarCollapsed}
        developerMode={app.developerMode}
        runtimeMode={app.runtimeMode}
        dragActive={app.dragActive}
        activeWorkspace={app.activeWorkspace}
        folderPath={app.folderPath}
        starterSummary={app.starterSummary}
        recentWorkspaces={app.recentWorkspaces}
        activeWorkspaceId={app.activeWorkspaceId}
        indexHistory={app.indexHistory}
        busy={app.busy}
        onToggleSidebar={() => app.setSidebarCollapsed((current) => !current)}
        onSetFolderPath={app.setFolderPath}
        onSetDragActive={app.setDragActive}
        onDropWorkspace={app.handleDropWorkspace}
        onIndexWorkspace={() => void app.handleIndex(app.folderPath)}
        onReindexWorkspace={() => app.activeWorkspace && void app.handleIndex(app.activeWorkspace.folderPath)}
        onClearWorkspace={app.clearActiveWorkspace}
        onToggleDeveloperMode={() => app.setDeveloperMode((current) => !current)}
        onSelectWorkspace={(workspaceId) => {
          app.setActiveWorkspaceId(workspaceId);
          app.setRoute("chat");
          void app.loadNotebookForWorkspace(workspaceId);
        }}
        formatDateTime={app.formatDateTime}
        formatRelative={app.formatRelative}
      />

      <main className="main-panel panel">
        <header className="main-header modern-header">
          <div className="main-header-copy">
            <div className="tabs" role="tablist" aria-label="Primary navigation">
              {app.visibleRoutes.map((item) => (
                <button key={item} className="tab" aria-selected={app.route === item} onClick={() => app.setRoute(item)}>
                  {item}
                </button>
              ))}
            </div>
            <div className="hero-inline">
              <div>
                <h2>{app.currentTitle}</h2>
                <p className="muted">{app.statusMessage}</p>
              </div>
              {app.route === "chat" && (
                <div className="toolbar compact">
                  <button className="context-toggle" onClick={() => { app.setContextTab("sources"); app.setContextPanelOpen((current) => !current); }}>
                    {app.contextPanelOpen ? "Hide Context" : "Show Context"}
                  </button>
                </div>
              )}
            </div>
            {app.errorMessage && <p className="error-banner" role="alert">{app.errorMessage}</p>}
          </div>
          <div className="header-badges">
            <div className="pill">{app.activeWorkspace?.title ?? "No workspace selected"}</div>
            <div className="pill">{app.indexedDocumentCount} docs</div>
          </div>
        </header>

        <div
          className={`main-scroll ${app.route === "chat" ? "chat-scroll" : ""}`}
          ref={app.route === "chat" ? app.chatScrollRef : undefined}
          onScroll={app.onChatScroll}
        >
          {app.route === "workspace" && (
            <WorkspaceRoute
              activeWorkspace={app.activeWorkspace}
              starterSummary={app.starterSummary}
              indexedDocumentCount={app.indexedDocumentCount}
              indexedPages={app.indexedPages}
              lastIndexEntry={app.lastIndexEntry}
              fileTypeSummary={app.fileTypeSummary}
              indexEvents={app.indexEvents}
              runtimeMode={app.runtimeMode}
              busy={app.busy}
              noBackend={app.noBackend}
              formatDateTime={app.formatDateTime}
              formatRelative={app.formatRelative}
            />
          )}

          {app.route === "chat" && (
            <ChatRoute
              busy={app.busy}
              chatMessages={app.chatMessages}
              allSourcesExpanded={app.allSourcesExpanded}
              sourceAccordionState={app.sourceAccordionState}
              sourceView={app.sourceView}
              onRetryLast={() => void app.handleRetryLast()}
              onRegenerate={() => void app.handleRegenerate()}
              onCancel={app.handleCancelResponse}
              onExportConversation={() => void app.exportConversation()}
              onSetChatInput={app.setChatInput}
              onCopyAnswer={(message) => void app.copyAnswer(message)}
              onRequestAnswer={(question) => void app.requestAnswer(question, "regenerate")}
              onOpenArtifact={(artifact) => void app.handleOpenArtifact(artifact)}
              onJumpToSource={(anchor) => void app.handleJumpToSource(anchor)}
              onCopyCitation={(chip) => void app.copyCitation(chip)}
              onToggleAccordion={(messageId, open) =>
                app.setSourceAccordionState((current) => ({ ...current, [messageId]: open }))
              }
              onToggleAllSources={() => app.setAllSourcesExpanded((current) => !current)}
            />
          )}

          {app.route === "notebook" && (
            <NotebookRoute
              notebook={app.notebook}
              artifactFilter={app.artifactFilter}
              artifactSearch={app.artifactSearch}
              artifactSort={app.artifactSort}
              filteredArtifacts={app.filteredArtifacts}
              artifactPreview={app.artifactPreview}
              noteOverrides={app.noteOverrides}
              pinnedArtifacts={app.pinnedArtifacts}
              formatDateTime={app.formatDateTime}
              onSetArtifactFilter={app.setArtifactFilter}
              onSetArtifactSearch={app.setArtifactSearch}
              onSetArtifactSort={app.setArtifactSort}
              onGoToChat={() => app.setRoute("chat")}
              onOpenArtifact={(artifact) => void app.handleOpenArtifact(artifact)}
              onTogglePin={(artifactId) =>
                app.setPinnedArtifacts((current) =>
                  current.includes(artifactId) ? current.filter((item) => item !== artifactId) : [artifactId, ...current],
                )
              }
              onRenameArtifact={app.renameArtifact}
              onExportArtifact={(artifact) => void app.exportArtifact(artifact)}
              onAskWithArtifact={(artifact) => {
                app.setChatInput(`Use artifact ${artifact.title} in answer.`);
                app.setRoute("chat");
              }}
              onDeleteArtifact={app.deleteArtifact}
            />
          )}

          {app.route === "quiz" && (
            <QuizRoute
              activeWorkspaceId={app.activeWorkspaceId}
              busy={app.busy}
              quizState={app.quizState}
              incorrectReviewOnly={app.incorrectReviewOnly}
              reviewItems={app.reviewItems}
              conceptSummary={app.conceptSummary}
              onStartQuiz={(restart) => void app.handleStartQuiz(restart)}
              onToggleIncorrectOnly={() => app.setIncorrectReviewOnly((current) => !current)}
              onRetryIncorrect={() => app.setIncorrectReviewOnly(true)}
              onAnswerQuiz={(choice) => void app.handleAnswerQuiz(choice)}
              onJumpToSource={(anchor) => void app.handleJumpToSource(anchor)}
            />
          )}

          {app.route === "source" && (
            <SourceRoute
              allCitationsCount={app.allCitations.length}
              sourceView={app.sourceView}
              sourceSearch={app.sourceSearch}
              sourceSearchResults={app.sourceSearchResults}
              sourcePanelExpanded={app.sourcePanelExpanded}
              quizSourceAnchor={app.quizState.sourceAnchor}
              onOpenQuizCitation={() => app.quizState.sourceAnchor && void app.handleJumpToSource(app.quizState.sourceAnchor)}
              onSourceNav={app.handleSourceNav}
              onCopySourceRef={() => void app.copySourceRef()}
              onToggleExpanded={() => app.setSourcePanelExpanded((current) => !current)}
              onSetSourceSearch={app.setSourceSearch}
            />
          )}

          {app.route === "developer" && app.developerMode && (
            <DeveloperRoute
              chatMessages={app.chatMessages}
              developerChunks={app.developerChunks}
              developerSummary={app.developerSummary}
              onBenchmarkImport={app.handleBenchmarkImport}
            />
          )}
        </div>

        {app.route === "chat" && (
          <Composer
            value={app.chatInput}
            inputRef={composerRef}
            activeWorkspaceId={app.activeWorkspaceId}
            busy={app.busy}
            onChange={app.setChatInput}
            onSubmit={() => void app.requestAnswer(app.chatInput, "new")}
            onCancel={app.handleCancelResponse}
          />
        )}
      </main>

      <ContextPanelRoute
        contextPanelOpen={app.contextPanelOpen}
        contextTab={app.contextTab}
        activeWorkspaceTitle={app.activeWorkspace?.title}
        notebook={app.notebook}
        sourceView={app.sourceView}
        sourceNavItems={app.sourceNavItems}
        filteredArtifacts={app.filteredArtifacts}
        noteOverrides={app.noteOverrides}
        pinnedArtifacts={app.pinnedArtifacts}
        quizState={app.quizState}
        reviewItems={app.reviewItems}
        onTogglePanel={() => app.setContextPanelOpen((current) => !current)}
        onSetContextTab={(tab) => {
          app.setContextTab(tab);
          app.setContextPanelOpen(true);
        }}
        onOpenSourceAnchor={(anchor) => void app.handleJumpToSource(anchor)}
        onOpenArtifact={(artifact) => void app.handleOpenArtifact(artifact)}
      />
    </div>
  );
}
