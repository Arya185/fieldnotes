import { EmptyState } from "../components/EmptyState";
import type { QuizReviewItem, QuizState } from "../lib/appState/types";

interface ConceptSummaryItem {
  id: string;
  name: string;
  touched: number;
  shaky: number;
}

interface QuizRouteProps {
  activeWorkspaceId: string | null;
  busy: boolean;
  quizState: QuizState;
  incorrectReviewOnly: boolean;
  reviewItems: QuizReviewItem[];
  conceptSummary: ConceptSummaryItem[];
  onStartQuiz: (restart?: boolean) => void;
  onToggleIncorrectOnly: () => void;
  onRetryIncorrect: () => void;
  onAnswerQuiz: (choice: number) => void;
  onJumpToSource: (anchor: string | undefined) => void;
}

export function QuizRoute({
  activeWorkspaceId,
  busy,
  quizState,
  incorrectReviewOnly,
  reviewItems,
  conceptSummary,
  onStartQuiz,
  onToggleIncorrectOnly,
  onRetryIncorrect,
  onAnswerQuiz,
  onJumpToSource,
}: QuizRouteProps) {
  return (
    <section className="workspace-overview stack">
      <div className="section-heading">
        <div>
          <div className="eyebrow">Quiz</div>
          <h3>Study mode</h3>
        </div>
      </div>
      <div className="toolbar">
        <button className="button" onClick={() => onStartQuiz(false)} disabled={!activeWorkspaceId || busy}>
          Start Quiz
        </button>
        <button className="button secondary" onClick={() => onStartQuiz(true)} disabled={!activeWorkspaceId || busy}>
          Restart Quiz
        </button>
        <button className="button ghost" onClick={onToggleIncorrectOnly} disabled={quizState.reviews.length === 0}>
          {incorrectReviewOnly ? "Show All Review" : "Incorrect Review"}
        </button>
      </div>
      {!quizState.question && !quizState.completion && (
        <EmptyState
          title="No quiz generated"
          body="Start quiz after indexing workspace. Fieldnotes builds questions from current source set."
          actionLabel="Generate Quiz"
          onAction={() => onStartQuiz(false)}
        />
      )}
      {quizState.question && (
        <article className="quiz-card study-card">
          <div className="quiz-kicker">Question</div>
          <div className="quiz-progress-row">
            <span className="pill">Progress {Math.min(quizState.reviews.length + 1, quizState.completion?.total ?? 1)}/{quizState.completion?.total ?? 1}</span>
            {quizState.reviews.length > 0 && <span className="pill">Score {quizState.reviews.filter((item) => item.isCorrect).length}</span>}
          </div>
          <strong className="quiz-question">{quizState.question}</strong>
          <div className="quiz-options">
            {quizState.options?.map((option, index) => (
              <button className="quiz-option" key={`${option}-${index}`} onClick={() => onAnswerQuiz(index)} disabled={busy}>
                {option}
              </button>
            ))}
          </div>
          {quizState.explanation && (
            <details className="quiz-explanation" open>
              <summary>Explanation</summary>
              <p>{quizState.explanation}</p>
            </details>
          )}
          {quizState.lastConcept && (
            <span className="pill">
              {quizState.lastConcept.name}: {quizState.lastConcept.state}
            </span>
          )}
        </article>
      )}
      {quizState.completion && (
        <div className="finish-card">
          <div className="eyebrow">Finish Screen</div>
          <h3>Completion summary: {quizState.completion.score}/{quizState.completion.total}</h3>
          <p>Review explanations, retry incorrect answers, or start fresh run when ready.</p>
          <div className="toolbar compact">
            <button className="button secondary" onClick={onRetryIncorrect} disabled={quizState.reviews.every((item) => item.isCorrect)}>
              Retry Incorrect
            </button>
            <button className="button ghost" onClick={() => onStartQuiz(true)}>
              Start Fresh
            </button>
          </div>
        </div>
      )}
      <div className="grid-two">
        <div className="history-list">
          {reviewItems.map((item, index) => (
            <div className="history-card" key={`${item.question}-${index}`}>
              <strong>{item.question}</strong>
              <p className="muted">You chose: {item.selectedLabel}</p>
              <p className="muted">Correct index: {item.correctIndex}</p>
              <p>{item.explanation}</p>
              {item.chip && (
                <button className="chip" onClick={() => onJumpToSource(item.chip?.anchor)}>
                  {item.chip.label}
                </button>
              )}
            </div>
          ))}
        </div>
        <div className="history-list">
          <div className="history-card">
            <strong>Concept Progress</strong>
            {conceptSummary.length === 0 && <p className="muted">No concept updates yet.</p>}
            {conceptSummary.map((concept) => (
              <div className="progress-meter" key={concept.id}>
                <span>{concept.name}</span>
                <div className="meter-bar">
                  <div className="meter-fill" style={{ width: `${Math.min(100, concept.touched * 25 + concept.shaky * 10)}%` }} />
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
      <div className="history-list">
        {quizState.progress.map((entry, index) => (
          <div className="history-card" key={`${entry}-${index}`}>
            {entry}
          </div>
        ))}
      </div>
    </section>
  );
}
