import { useRef } from "react";

import { openAskStream } from "./api";
import type { AskEvent } from "../types";

export function useAskStream() {
  const abortRef = useRef<AbortController | null>(null);

  async function runAskStream(
    workspaceId: string,
    question: string,
    onEvent: (event: AskEvent) => void | Promise<void>,
    onAbort: () => void,
    onError: (error: Error) => void,
  ): Promise<void> {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    await openAskStream(
      { workspace_id: workspaceId, question },
      onEvent,
      controller.signal,
    ).catch((error: Error) => {
      if (error.name === "AbortError") {
        onAbort();
        return;
      }
      onError(error);
    });
  }

  function cancelAskStream() {
    abortRef.current?.abort();
  }

  return { runAskStream, cancelAskStream };
}
