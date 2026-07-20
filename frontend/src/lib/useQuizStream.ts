import { openQuizAnswerStream, openQuizStartStream } from "./api";
import type { QuizEvent } from "../types";

export function useQuizStream() {
  async function startQuizStream(
    workspaceId: string,
    onEvent: (event: QuizEvent) => void,
    onError: (error: Error) => void,
  ): Promise<void> {
    await openQuizStartStream(
      { workspace_id: workspaceId, concept_ids: null },
      onEvent,
    ).catch(onError);
  }

  async function answerQuizStream(
    workspaceId: string,
    attemptId: string,
    choice: number,
    onEvent: (event: QuizEvent) => void,
    onError: (error: Error) => void,
  ): Promise<void> {
    await openQuizAnswerStream(
      { workspace_id: workspaceId, attempt_id: attemptId, chosen_index: choice },
      onEvent,
    ).catch(onError);
  }

  return { startQuizStream, answerQuizStream };
}
