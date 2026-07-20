import type { Dispatch, RefObject, SetStateAction, UIEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";

import { getSource } from "../api";
import { useAskStream } from "../useAskStream";
import type { AskEvent, CitationChip } from "../../types";
import type {
  ChatMessage,
  ContextTab,
  DeveloperChunk,
  RouteKey,
  SourceAccordionState,
  SourceNavItem,
  SourceViewState,
} from "./types";
import { copyText } from "./utils";

interface UseAskStateArgs {
  activeWorkspaceId: string | null;
  route: RouteKey;
  composerRef: RefObject<HTMLTextAreaElement | null>;
  loadNotebookForWorkspace: (workspaceId: string) => Promise<void>;
  handleJumpToSource: (anchor: string | undefined, citationIndex?: number) => Promise<void>;
  setBusy: Dispatch<SetStateAction<boolean>>;
  setErrorMessage: Dispatch<SetStateAction<string | null>>;
  setStatusMessage: Dispatch<SetStateAction<string>>;
  setContextTab: Dispatch<SetStateAction<ContextTab>>;
  setContextPanelOpen: Dispatch<SetStateAction<boolean>>;
}

export function useAskState({
  activeWorkspaceId,
  route,
  composerRef,
  loadNotebookForWorkspace,
  handleJumpToSource,
  setBusy,
  setErrorMessage,
  setStatusMessage,
  setContextTab,
  setContextPanelOpen,
}: UseAskStateArgs) {
  const [chatInput, setChatInput] = useState("");
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [developerChunks, setDeveloperChunks] = useState<DeveloperChunk[]>([]);
  const [streamingAnswerId, setStreamingAnswerId] = useState<string | null>(null);
  const [typingIndicator, setTypingIndicator] = useState(false);
  const [allSourcesExpanded, setAllSourcesExpanded] = useState(false);
  const [sourceAccordionState, setSourceAccordionState] = useState<SourceAccordionState>({});
  const chatScrollRef = useRef<HTMLDivElement | null>(null);
  const autoScrollRef = useRef(true);
  const { runAskStream, cancelAskStream } = useAskStream();

  useEffect(() => {
    if (route === "chat") {
      composerRef.current?.focus();
    }
  }, [composerRef, route]);

  useEffect(() => {
    const node = chatScrollRef.current;
    if (!node || route !== "chat" || !autoScrollRef.current) {
      return;
    }
    node.scrollTop = node.scrollHeight;
  }, [chatMessages, route, typingIndicator]);

  const allCitations = useMemo(
    () =>
      chatMessages.flatMap((message) =>
        message.citations.map((chip) => ({
          messageId: message.id,
          label: chip.label,
          anchor: chip.anchor,
        })),
      ),
    [chatMessages],
  );

  const sourceNavItems = useMemo<SourceNavItem[]>(
    () =>
      allCitations.slice(0, 10).map((citation) => ({
        label: citation.label,
        anchor: citation.anchor,
      })),
    [allCitations],
  );

  async function requestAnswer(userText: string, mode: "new" | "retry" | "regenerate") {
    if (!activeWorkspaceId || !userText.trim()) {
      return;
    }
    setErrorMessage(null);
    const userMessage: ChatMessage | null =
      mode === "new"
        ? {
            id: `user-${Date.now()}`,
            role: "user",
            text: userText,
            artifacts: [],
            citations: [],
            concepts: [],
            steps: [],
            requestText: userText,
          }
        : null;
    const assistantMessage: ChatMessage = {
      id: `assistant-${Date.now()}`,
      role: "assistant",
      text: "",
      artifacts: [],
      citations: [],
      concepts: [],
      steps: [],
      pending: true,
      requestText: userText,
    };
    setChatInput("");
    setBusy(true);
    setTypingIndicator(true);
    setStatusMessage("Streaming answer...");
    setDeveloperChunks([]);
    setStreamingAnswerId(assistantMessage.id);
    setChatMessages((current) => (mode === "new" ? [...current, userMessage!, assistantMessage] : [...current, assistantMessage]));

    await runAskStream(
      activeWorkspaceId,
      userText,
      async (event: AskEvent) => {
        setChatMessages((current) =>
          current.map((message) => {
            if (message.id !== assistantMessage.id) {
              return message;
            }
            if (event.event === "intent") {
              return { ...message, answerId: event.answer_id };
            }
            if (event.event === "token") {
              return { ...message, answerId: event.answer_id, text: `${message.text}${event.text}`, pending: false };
            }
            if (event.event === "artifact") {
              return { ...message, answerId: event.answer_id, artifacts: [...message.artifacts, event], pending: false };
            }
            if (event.event === "citations") {
              return { ...message, answerId: event.answer_id, citations: event.chips, pending: false };
            }
            if (event.event === "concepts") {
              return { ...message, answerId: event.answer_id, concepts: event.updates, pending: false };
            }
            if (event.event === "step") {
              return { ...message, answerId: event.answer_id, steps: [...message.steps, `${event.step}: ${event.label}`], pending: true };
            }
            if (event.event === "error") {
              return {
                ...message,
                answerId: event.answer_id,
                error: event.message,
                text: `${message.text}\n\nError: ${event.message}`.trim(),
                pending: false,
              };
            }
            if (event.event === "done") {
              return { ...message, answerId: event.answer_id, pending: false };
            }
            return message;
          }),
        );

        if (event.event === "citations") {
          const chunks = await Promise.all(
            event.chips
              .filter((chip) => chip.anchor && chip.anchor.includes("#"))
              .map(async (chip) => {
                const [fileId, locator] = chip.anchor!.split("#");
                const response = await getSource(activeWorkspaceId, fileId, locator);
                return { label: chip.label, chunk: response.text };
              }),
          );
          setDeveloperChunks(chunks);
        }

        if (event.event === "done") {
          setBusy(false);
          setTypingIndicator(false);
          setStreamingAnswerId(null);
          setStatusMessage("Answer complete.");
          void loadNotebookForWorkspace(activeWorkspaceId);
        }
      },
      () => {
        setStatusMessage("Response canceled.");
        setTypingIndicator(false);
        setBusy(false);
        setStreamingAnswerId(null);
      },
      (error: Error) => {
        setBusy(false);
        setTypingIndicator(false);
        setStreamingAnswerId(null);
        setErrorMessage(`Ask failed: ${error.message}`);
        setStatusMessage(error.message);
        setChatMessages((current) =>
          current.map((message) =>
            message.id === assistantMessage.id
              ? { ...message, error: error.message, pending: false, text: message.text || `Error: ${error.message}` }
              : message,
          ),
        );
      },
    );
  }

  function handleCancelResponse() {
    cancelAskStream();
    setTypingIndicator(false);
    setBusy(false);
    setChatMessages((current) =>
      current.map((message) =>
        message.id === streamingAnswerId
          ? { ...message, pending: false, error: "Canceled by user." }
          : message,
      ),
    );
  }

  async function handleRetryLast() {
    const lastPrompt = [...chatMessages].reverse().find((message) => message.role === "user")?.text;
    if (!lastPrompt) {
      return;
    }
    await requestAnswer(lastPrompt, "retry");
  }

  async function handleRegenerate() {
    const lastPrompt = [...chatMessages].reverse().find((message) => message.role === "user")?.text;
    if (!lastPrompt) {
      return;
    }
    await requestAnswer(lastPrompt, "regenerate");
  }

  async function exportConversation() {
    const content = chatMessages
      .map((message) => {
        const title = message.role === "assistant" ? "## Fieldnotes" : "## You";
        const citations =
          message.citations.length > 0
            ? `\n\nCitations:\n${message.citations.map((chip) => `- ${chip.label}${chip.anchor ? ` (${chip.anchor})` : ""}`).join("\n")}`
            : "";
        return `${title}\n\n${message.text}${citations}`;
      })
      .join("\n\n");
    await copyText(content);
    setStatusMessage("Conversation markdown copied.");
  }

  async function copyCitation(chip: CitationChip) {
    await copyText(`${chip.label}${chip.anchor ? ` (${chip.anchor})` : ""}`);
    setStatusMessage("Citation copied.");
  }

  async function copyAnswer(message: ChatMessage) {
    await copyText(message.text);
    setStatusMessage("Answer copied.");
  }

  function onChatScroll(event: UIEvent<HTMLDivElement>) {
    if (route !== "chat") {
      return;
    }
    const node = event.currentTarget;
    const nearBottom = node.scrollHeight - node.scrollTop - node.clientHeight < 64;
    autoScrollRef.current = nearBottom;
  }

  async function openCitation(anchor: string | undefined) {
    const citationIndex = allCitations.findIndex((item) => item.anchor === anchor);
    await handleJumpToSource(anchor, citationIndex >= 0 ? citationIndex : undefined);
    setContextTab("sources");
    setContextPanelOpen(true);
  }

  return {
    chatInput,
    setChatInput,
    chatMessages,
    setChatMessages,
    developerChunks,
    streamingAnswerId,
    typingIndicator,
    allSourcesExpanded,
    setAllSourcesExpanded,
    sourceAccordionState,
    setSourceAccordionState,
    chatScrollRef,
    allCitations,
    sourceNavItems,
    requestAnswer,
    handleCancelResponse,
    handleRetryLast,
    handleRegenerate,
    exportConversation,
    copyCitation,
    copyAnswer,
    onChatScroll,
    openCitation,
  };
}
