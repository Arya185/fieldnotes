import type { Dispatch, SetStateAction } from "react";
import { useMemo, useState } from "react";

import { useQuizStream } from "../useQuizStream";
import type { QuizEvent } from "../../types";
import type { ChatMessage, ConceptSummaryItem, QuizState } from "./types";

interface UseQuizStateArgs {
  activeWorkspaceId: string | null;
  chatMessages: ChatMessage[];
  loadNotebookForWorkspace: (workspaceId: string) => Promise<void>;
  setBusy: Dispatch<SetStateAction<boolean>>;
  setErrorMessage: Dispatch<SetStateAction<string | null>>;
  setStatusMessage: Dispatch<SetStateAction<string>>;
}

export function useQuizState({
  activeWorkspaceId,
  chatMessages,
  loadNotebookForWorkspace,
  setBusy,
  setErrorMessage,
  setStatusMessage,
}: UseQuizStateArgs) {
  const [quizState, setQuizState] = useState<QuizState>({ progress: [], reviews: [] });
  const [incorrectReviewOnly, setIncorrectReviewOnly] = useState(false);
  const { startQuizStream, answerQuizStream } = useQuizStream();

  const conceptSummary = useMemo<ConceptSummaryItem[]>(() => {
    const map = new Map<string, { name: string; touched: number; shaky: number }>();
    chatMessages.flatMap((message) => message.concepts).forEach((concept) => {
      const current = map.get(concept.concept_id) ?? { name: concept.name, touched: 0, shaky: 0 };
      if (concept.state === "touched") {
        current.touched += 1;
      } else {
        current.shaky += 1;
      }
      map.set(concept.concept_id, current);
    });
    quizState.reviews.forEach((review) => {
      if (!review.concept) {
        return;
      }
      const current = map.get(review.concept.concept_id) ?? { name: review.concept.name, touched: 0, shaky: 0 };
      if (review.concept.state === "touched") {
        current.touched += 1;
      } else {
        current.shaky += 1;
      }
      map.set(review.concept.concept_id, current);
    });
    return [...map.entries()].map(([id, value]) => ({ id, ...value }));
  }, [chatMessages, quizState.reviews]);

  const reviewItems = incorrectReviewOnly
    ? quizState.reviews.filter((item) => !item.isCorrect)
    : quizState.reviews;

  async function handleStartQuiz(restart = false) {
    if (!activeWorkspaceId) {
      return;
    }
    setBusy(true);
    setErrorMessage(null);
    setStatusMessage(restart ? "Restarting quiz..." : "Generating quiz...");
    await startQuizStream(
      activeWorkspaceId,
      (event: QuizEvent) => {
        if (event.event === "question") {
          setQuizState((current) => ({
            ...current,
            attemptId: event.attempt_id,
            question: event.question,
            options: event.options,
            sourceLabel: event.source_label,
            sourceAnchor: event.source_anchor,
            explanation: undefined,
            lastConcept: undefined,
            completion: undefined,
            progress: restart ? [`Question: ${event.question}`] : [...current.progress, `Question: ${event.question}`],
          }));
          setBusy(false);
          setStatusMessage("Quiz ready.");
        }
      },
      (error: Error) => {
        setBusy(false);
        setErrorMessage(`Quiz start failed: ${error.message}`);
        setStatusMessage(error.message);
      },
    );
  }

  async function handleAnswerQuiz(choice: number) {
    if (!activeWorkspaceId || !quizState.attemptId || !quizState.question) {
      return;
    }
    setBusy(true);
    setStatusMessage("Checking answer...");
    await answerQuizStream(
      activeWorkspaceId,
      quizState.attemptId,
      choice,
      (event: QuizEvent) => {
        if (event.event === "graded") {
          setQuizState((current) => ({
            ...current,
            explanation: event.explanation,
            lastConcept: event.concept_update,
            reviews: [
              ...current.reviews,
              {
                question: current.question ?? "",
                selectedIndex: choice,
                selectedLabel: current.options?.[choice] ?? "",
                correctIndex: event.correct_index,
                isCorrect: event.is_correct,
                explanation: event.explanation,
                chip: event.chip,
                concept: event.concept_update,
              },
            ],
            progress: [...current.progress, `Graded: ${event.is_correct ? "correct" : "incorrect"}`],
          }));
        }
        if (event.event === "quiz_done") {
          setQuizState((current) => ({
            ...current,
            completion: { score: event.score, total: event.total },
            progress: [...current.progress, `Done: ${event.score}/${event.total}`],
          }));
          setBusy(false);
          setStatusMessage("Quiz complete.");
          void loadNotebookForWorkspace(activeWorkspaceId);
        }
      },
      (error: Error) => {
        setBusy(false);
        setErrorMessage(`Quiz answer failed: ${error.message}`);
        setStatusMessage(error.message);
      },
    );
  }

  return {
    quizState,
    setQuizState,
    incorrectReviewOnly,
    setIncorrectReviewOnly,
    conceptSummary,
    reviewItems,
    handleStartQuiz,
    handleAnswerQuiz,
  };
}
