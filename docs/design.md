# Fieldnotes — UI/UX Design

**Version:** 1.0
**Date:** July 17, 2026
**Companions:** prd.md, techstack.md, dataflow.md

---

## 1. Design principles

1. **Make the agent's work visible.** The router trace is the hero element of the product — every answer shows what the agent decided and did. This is the visual proof that Fieldnotes is an agentic system, not chat-with-PDF.
2. **Grounding is one click away everywhere.** Every answer ends in citation chips; sources and generated code are always inspectable.
3. **The workspace accumulates.** Artifacts persist in the notebook; nothing valuable scrolls away.
4. **Privacy is ambient, not a settings page.** The "local workspace" lock badge is always visible in the header.
5. **The system speaks first.** After indexing, Fieldnotes proves comprehension (brief + starter cards) before the student has to think of a question — no blank chat box, no cold start.

---

## 2. Information architecture

Single-page application, three persistent panes plus a header. The center pane swaps content by state; the side panes never unmount.

```
┌──────────────────────────────────────────────────────────────┐
│ Header: course name · 🔒 local workspace badge               │
├────────────┬─────────────────────────────────┬───────────────┤
│ LEFT       │ CENTER                          │ RIGHT         │
│ Files      │ Investigation thread            │ Notebook      │
│ Concept    │ (or quiz state / onboarding)    │ (artifacts)   │
│ log        │ Input + "Quiz me"               │               │
└────────────┴─────────────────────────────────┴───────────────┘
```

---

## 3. Screens and states

### 3.1 Onboarding — workspace brief

Shown ~30 seconds after folder selection. A **card, not a chat** — it proves comprehension before any typing.

- **Header row:** folder icon, course title (inferred), path + "indexed locally · N files" metadata, green "Ready" pill.
- **Inventory counts row:** metric cards (textbook chapters / lecture decks / datasets). Doubles as an index audit — a student instantly spots if a file failed to parse.
- **Comprehension paragraph:** one short paragraph summarizing what the course appears to be and what was found (mentions concrete artifacts: "pendulum experiment data with 5 trials").
- **Starter cards:** 3–4 tappable buttons, each generated from the actual index and **naming a real file**, e.g.:
  - "Trial 4 in pendulum_data.csv deviates from the others — investigate?" (seeded by outlier detection)
  - "Explain damped oscillation using Chapter 6 and lecture 8"
  - "Quiz me on resonance before Thursday's lab"

### 3.2 Indexing state

- Per-file tick-off list with a live one-line comprehension summary per file ("parsed pendulum.csv — 5 trials, 200 rows"), streamed over SSE.
- Design intent: the 20–30 second wait reads as **intelligence, not loading**.

### 3.3 Main workspace — investigation thread

- **Left pane — files + concept log:**
  - Indexed file list with type icons; the file currently being analyzed is highlighted (accent background).
  - Concept log chips below: **amber = shaky** (asked about repeatedly or missed in a quiz), **neutral = touched**. Ambient — the student never manages it; it visibly grows during a session.
- **Center pane — thread:**
  - User messages right-aligned in accent bubbles.
  - **Router trace strip** under each question: thin, monospace, bordered row showing intent + execution steps with checkmarks and timing:
    `agent · analyze ✓ read pendulum.csv → wrote analysis.py → ran locally · 1.8s ✓ matched ch6_damping.pdf §6.3`
    The strip varies by intent (`retrieve ✓ 3 passages from ch5`, `quiz ✓ 6 questions from concept log`). Rendered directly from SSE `step` events.
  - Answer body: prose, inline chart (PNG from backend) where relevant.
  - **Citation chips** at the end of every answer: document chips (open the source passage at its anchor in a drawer) and code chips (open the actual generated `analysis.py` and its captured output in a drawer).
  - **Input row:** text input ("Ask about your course…") + persistent **"Quiz me"** button — practice is one click from anywhere, not a mode switch.
- **Right pane — notebook:**
  - Timestamped artifact cards (chart / explainer / quiz with score), newest first.
  - "Open notebook" expands to a full notebook page.

### 3.4 Quiz state

- Takes over the **center pane only** — sidebar and notebook stay mounted, reinforcing continuity.
- One question at a time; **the source file is cited under each question** ("from ch5_shm.pdf §5.2") — reinforcing that questions come from the student's own material.
- On a wrong answer: brief grounded correction with a citation chip; the concept turns amber in the left pane in real time.
- On completion: score card saved to the notebook; suggested starting points refresh (loop closure made visible).

---

## 4. Component inventory

| Component | Purpose | Key behavior |
|---|---|---|
| RouterTrace | Prove the agentic layer per answer | Streams from SSE `step` events; monospace; checkmarks + timing |
| CitationChips | Grounding | Document chips → passage drawer at anchor; code chips → script + output drawer |
| StarterCards | Kill the cold start | Generated from index; each names a real file; tap = sends the question |
| ConceptChips | Ambient learning state | Neutral (touched) / amber (shaky); updates live during quizzes |
| NotebookCard | Persistence | Icon + title + relative timestamp; click opens artifact |
| LockBadge | Privacy claim | Header, always visible: "🔒 local workspace" |
| MetricCards | Index audit | Inventory counts on the brief |
| QuizCard | Practice | One question, source citation, immediate grounded feedback |
| InputRow | Entry point | Text input + persistent "Quiz me" button |
| IndexProgress | Onboarding wait | Per-file tick-off + comprehension line |

---

## 5. Visual language

- **Layout:** flat, clean surfaces; hairline borders (0.5px); generous whitespace; 8–12px corner radii; no gradients or shadows.
- **Typography:** one sans family; two weights (regular/medium); monospace reserved exclusively for the router trace and code — the trace's typographic contrast is deliberate, marking "machine work" inside a conversational surface.
- **Color roles (semantic, not decorative):**
  - Accent (blue/purple family): user messages, active file highlight, links.
  - Success (green): "Ready" pill, trace checkmarks.
  - Warning (amber): shaky concept chips — the only alarm color in normal use.
  - Anomaly highlight (coral/orange): reserved for the data being investigated (e.g., the Trial 4 line in charts), matching chart to narrative.
  - Neutral grays: everything else.
- **Charts:** minimal — axes, series, direct labels on the plot (no legends where avoidable); the anomalous series in the accent-anomaly color, comparison series muted gray.
- **Density:** compact side panes (11–12px labels), comfortable center pane (13–14px body).
- **Dark mode:** in scope only if trivially available from the component library; not a v1 requirement.

## 6. Content voice

- Sentence case everywhere; no exclamation marks in system copy.
- Comprehension lines are concrete and specific ("5 trials, 200 rows"), never generic ("Processing…").
- Starter cards are phrased as invitations with a question mark or an imperative, and always name a file.
- Trace steps are terse past-tense fragments ("wrote analysis.py", "ran locally · 1.8s").
- Errors say what happened and what happens next ("Analysis failed on first attempt — retrying with the error in context").

---

## 7. Interaction details

- **SSE-driven progressive rendering:** intent appears first, then steps tick in, then answer prose streams, then chips — the answer *assembles* in front of the student, which is both honest and demo-friendly.
- **File highlight sync:** when the trace emits `read pendulum.csv`, the left-pane file highlights simultaneously.
- **Drawer pattern** for citations: passages and code open in an overlay drawer from the right; the thread never navigates away.
- **Concept chip transitions:** neutral → amber animates subtly on a missed quiz answer; the moment is visible without being noisy.
- **Empty states:** notebook shows "Artifacts you generate will collect here" before first use; concept log area hidden until the first concept is logged.

---

## 8. Demo-critical moments (design checklist)

1. Brief appears with real file names in the starter cards — comprehension proven (wow 1).
2. Router trace streams during the Trial 4 investigation; code chip opens the actual generated script (wow 2).
3. Missed quiz answer flips a concept chip to amber and the starter cards refresh — loop closed on screen (wow 3).
4. Lock badge visible in every shot for the one-sentence privacy close.

Every one of these must read clearly in a compressed YouTube video at 1080p — check contrast and font sizes against that bar, not just the local display.
