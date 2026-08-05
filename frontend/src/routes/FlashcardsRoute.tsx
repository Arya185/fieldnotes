import { useEffect, useMemo, useState } from "react";

import { EmptyState } from "../components/EmptyState";
import { generateFlashcards, getFlashcards, reviewFlashcard } from "../lib/api";
import type { ConfidenceRating, Flashcard } from "../types";

interface FlashcardsRouteProps {
  activeWorkspaceId: string | null;
}

const CONFIDENCE_BUTTONS: { rating: ConfidenceRating; label: string; className: string }[] = [
  { rating: "again", label: "Again", className: "danger" },
  { rating: "hard", label: "Hard", className: "" },
  { rating: "good", label: "Good", className: "" },
  { rating: "easy", label: "Easy", className: "success" },
];

function difficultyTone(difficulty: Flashcard["difficulty"]): string {
  if (difficulty === "hard") {
    return "danger";
  }
  if (difficulty === "medium") {
    return "";
  }
  return "success";
}

function masteryPercent(card: Flashcard): number {
  return Math.round(Math.max(0, Math.min(1, card.mastery_weight)) * 100);
}

export function FlashcardsRoute({ activeWorkspaceId }: FlashcardsRouteProps) {
  const [flashcards, setFlashcards] = useState<Flashcard[]>([]);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [studyMode, setStudyMode] = useState(false);
  const [studyQueue, setStudyQueue] = useState<Flashcard[]>([]);
  const [studyIndex, setStudyIndex] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [sessionReviewed, setSessionReviewed] = useState(0);
  const [lastNote, setLastNote] = useState<string | null>(null);

  async function loadFlashcards() {
    if (!activeWorkspaceId) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await getFlashcards(activeWorkspaceId);
      setFlashcards(data.flashcards);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadFlashcards();
  }, [activeWorkspaceId]);

  async function handleGenerate() {
    if (!activeWorkspaceId) {
      return;
    }
    setGenerating(true);
    setError(null);
    try {
      await generateFlashcards({ workspace_id: activeWorkspaceId, count: 10 });
      await loadFlashcards();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setGenerating(false);
    }
  }

  function startStudyMode() {
    const today = new Date().toISOString().slice(0, 10);
    const due = flashcards.filter((card) => card.next_review <= today);
    const queue = due.length > 0 ? due : flashcards;
    setStudyQueue(queue);
    setStudyIndex(0);
    setFlipped(false);
    setSessionReviewed(0);
    setLastNote(null);
    setStudyMode(true);
  }

  const currentCard = studyQueue[studyIndex];

  async function handleConfidence(rating: ConfidenceRating) {
    if (!activeWorkspaceId || !currentCard) {
      return;
    }
    try {
      const result = await reviewFlashcard({
        workspace_id: activeWorkspaceId,
        flashcard_id: currentCard.id,
        confidence: rating,
      });
      setFlashcards((current) =>
        current.map((card) => (card.id === result.flashcard.id ? result.flashcard : card)),
      );
      setSessionReviewed((count) => count + 1);
      setLastNote(
        result.generated_more
          ? "Mastery is low for this topic — more flashcards were generated."
          : result.topic_mastery !== null
            ? `Topic mastery now ${Math.round((result.topic_mastery ?? 0) * 100)}%.`
            : null,
      );
      setFlipped(false);
      setStudyIndex((index) => index + 1);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  const dueCount = useMemo(() => {
    const today = new Date().toISOString().slice(0, 10);
    return flashcards.filter((card) => card.next_review <= today).length;
  }, [flashcards]);

  if (!activeWorkspaceId) {
    return (
      <section className="workspace-overview stack">
        <EmptyState
          title="No workspace selected"
          body="Select or index a workspace to generate and study flashcards."
        />
      </section>
    );
  }

  if (studyMode) {
    return (
      <section className="workspace-overview stack">
        <div className="section-heading">
          <div>
            <div className="eyebrow">Flashcards</div>
            <h3>Study mode</h3>
          </div>
          <button className="button ghost" onClick={() => setStudyMode(false)}>
            Exit Study Mode
          </button>
        </div>

        {!currentCard ? (
          <div className="finish-card">
            <div className="eyebrow">Session complete</div>
            <h3>Reviewed {sessionReviewed} card{sessionReviewed === 1 ? "" : "s"}</h3>
            <p>Nice work. Come back later for the next spaced-repetition round.</p>
            <div className="toolbar compact">
              <button className="button" onClick={startStudyMode}>
                Study Again
              </button>
              <button className="button ghost" onClick={() => setStudyMode(false)}>
                Back to Flashcards
              </button>
            </div>
          </div>
        ) : (
          <>
            <div className="quiz-progress-row">
              <span className="pill">
                Card {studyIndex + 1}/{studyQueue.length}
              </span>
              <span className={`pill ${difficultyTone(currentCard.difficulty)}`}>
                {currentCard.difficulty}
              </span>
              <span className="pill">{currentCard.card_type.replace("_", " ")}</span>
              <span className="pill">{currentCard.bloom_level}</span>
            </div>

            <div
              className={`flip-card ${flipped ? "is-flipped" : ""}`}
              onClick={() => setFlipped((value) => !value)}
              role="button"
              tabIndex={0}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  setFlipped((value) => !value);
                }
              }}
            >
              <div className="flip-card-inner">
                <div className="flip-card-face flip-card-front">
                  <div className="quiz-kicker">Question</div>
                  <strong className="quiz-question">{currentCard.question}</strong>
                  <p className="muted">Tap card to reveal answer.</p>
                </div>
                <div className="flip-card-face flip-card-back">
                  <div className="quiz-kicker">Answer</div>
                  <p className="quiz-question">{currentCard.answer}</p>
                  <button
                    className="chip"
                    onClick={(event) => event.stopPropagation()}
                  >
                    {currentCard.source_document} {currentCard.source_locator}
                  </button>
                </div>
              </div>
            </div>

            {flipped && (
              <div className="confidence-buttons">
                {CONFIDENCE_BUTTONS.map((option) => (
                  <button
                    key={option.rating}
                    className={`button ${option.className}`.trim()}
                    onClick={() => void handleConfidence(option.rating)}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            )}

            {lastNote && <p className="muted">{lastNote}</p>}
          </>
        )}
      </section>
    );
  }

  return (
    <section className="workspace-overview stack">
      <div className="section-heading">
        <div>
          <div className="eyebrow">Flashcards</div>
          <h3>Spaced-repetition flashcards</h3>
        </div>
      </div>
      <div className="toolbar">
        <button className="button" onClick={handleGenerate} disabled={generating}>
          {generating ? "Generating..." : "Generate Flashcards"}
        </button>
        <button className="button secondary" onClick={startStudyMode} disabled={flashcards.length === 0}>
          Start Study Mode
        </button>
        <span className="pill">{flashcards.length} cards</span>
        <span className={`pill ${dueCount > 0 ? "success" : ""}`}>{dueCount} due</span>
      </div>

      {error && (
        <p className="error-banner" role="alert">
          {error}
        </p>
      )}

      {loading && <p className="muted">Loading flashcards...</p>}

      {!loading && flashcards.length === 0 && (
        <EmptyState
          title="No flashcards yet"
          body="Generate flashcards from your indexed documents to start spaced-repetition study."
          actionLabel="Generate Flashcards"
          onAction={() => void handleGenerate()}
        />
      )}

      {!loading && flashcards.length > 0 && (
        <div className="flashcard-grid">
          {flashcards.map((card) => (
            <article className="history-card compact-card" key={card.id}>
              <header>
                <span className={`pill ${difficultyTone(card.difficulty)}`}>{card.difficulty}</span>
                <span className="pill">{card.card_type.replace("_", " ")}</span>
              </header>
              <strong>{card.question}</strong>
              <p className="muted">{card.answer}</p>
              <div className="progress-meter">
                <span>Mastery</span>
                <div className="meter-bar">
                  <div className="meter-fill accent" style={{ width: `${masteryPercent(card)}%` }} />
                </div>
              </div>
              <p className="muted">
                Next review {card.next_review} · {card.review_count} review{card.review_count === 1 ? "" : "s"}
              </p>
              <button className="chip">
                {card.source_document} {card.source_locator}
              </button>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
