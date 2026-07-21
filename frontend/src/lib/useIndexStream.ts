import { useRef } from "react";

import { openIndexEvents } from "./api";
import type { IndexEvent } from "../types";

export function useIndexStream() {
  const abortRef = useRef<AbortController | null>(null);

  async function startIndexStream(
    eventsPath: string,
    onEvent: (event: IndexEvent) => void,
    onError: (error: Error) => void,
  ): Promise<void> {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    await openIndexEvents(eventsPath, onEvent, controller.signal).catch((error: Error) => {
      if (error.name === "AbortError") {
        return;
      }
      onError(error);
    });
  }

  return { startIndexStream };
}
