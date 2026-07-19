import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";

function makeSseResponse(events: unknown[]) {
  const text = events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join("");
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(text));
      controller.close();
    },
  });
  return new Response(stream, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

function makeJsonResponse(payload: unknown) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("Fieldnotes frontend", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.location.hash = "";
    Object.assign(navigator, {
      clipboard: {
        writeText: vi.fn(async () => undefined),
      },
    });
    window.confirm = vi.fn(() => true);
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/index") && init?.method === "POST") {
        const payload = init.body ? (JSON.parse(String(init.body)) as { folder_path?: string }) : {};
        const isBeta = payload.folder_path?.includes("beta");
        const workspaceId = isBeta ? "ws_beta" : "ws_alpha";
        const runId = isBeta ? "run_beta" : "run_alpha";
        return makeJsonResponse({
          status: "accepted",
          workspace_id: workspaceId,
          run_id: runId,
          events: `/index/events/${runId}`,
        });
      }
      if (url.endsWith("/index/events/run_alpha") || url.endsWith("/index/events/run_beta")) {
        return makeSseResponse([
          { event: "file_started", file_id: "file_alpha", display_name: "alpha.txt" },
          {
            event: "file_parsed",
            file_id: "file_alpha",
            display_name: "alpha.txt",
            parse_status: "parsed",
            parse_summary: "parsed alpha.txt - 1 chunks",
          },
          { event: "index_complete", file_count: 1, chunk_count: 1 },
          {
            event: "brief_ready",
            brief: {
              course_title: "alpha",
              summary: "Indexed 1 file.",
              starter_cards: [
                { text: "Open alpha", file_path: "alpha.txt", seed: "concept" },
                { text: "Explore alpha", file_path: "alpha.txt", seed: "practice" },
                { text: "Review alpha", file_path: "alpha.txt", seed: "concept" },
              ],
            },
          },
        ]);
      }
      if (url.endsWith("/ask")) {
        return makeSseResponse([
          { event: "intent", answer_id: "a1", intent: "retrieve", targets: [], connect: false },
          { event: "step", answer_id: "a1", step: "retrieval", label: "searching selected workspace", status: "started" },
          { event: "token", answer_id: "a1", text: "Grounded answer " },
          { event: "token", answer_id: "a1", text: "with citation." },
          { event: "artifact", answer_id: "a1", artifact_id: "artifact_1", kind: "explainer", title: "Answer artifact", url: "/artifact/artifact_1" },
          {
            event: "citations",
            answer_id: "a1",
            chips: [{ chip_type: "document", label: "alpha.txt block1", anchor: "file_alpha#block1/b1" }],
          },
          {
            event: "concepts",
            answer_id: "a1",
            updates: [{ concept_id: "concept_alpha", name: "alpha", state: "touched" }],
          },
          { event: "done", answer_id: "a1" },
        ]);
      }
      if (url.includes("/notebook?workspace_id=ws_alpha")) {
        return makeJsonResponse({
          artifacts: [
            {
              id: "artifact_1",
              kind: "explainer",
              title: "Answer artifact",
              created_at: "2026-07-18T00:00:00Z",
              url: "/artifact/artifact_1",
            },
            {
              id: "artifact_2",
              kind: "chart",
              title: "Chart artifact",
              created_at: "2026-07-18T00:00:00Z",
              url: "/artifact/artifact_2",
            },
          ],
        });
      }
      if (url.includes("/artifact/artifact_1")) {
        return new Response("## Explainer\n\nhello", {
          status: 200,
          headers: { "Content-Type": "text/plain" },
        });
      }
      if (url.includes("/artifact/artifact_2")) {
        return new Response("fake-image", {
          status: 200,
          headers: { "Content-Type": "image/png" },
        });
      }
      if (url.includes("/quiz/start")) {
        return makeSseResponse([
          {
            event: "question",
            attempt_id: "attempt_1",
            index: 1,
            total: 1,
            question: "Which file contains alpha?",
            options: ["alpha.txt", "beta.txt", "gamma.txt", "delta.txt"],
            source_label: "alpha.txt block1",
            source_anchor: "file_alpha#block1/b1",
          },
        ]);
      }
      if (url.includes("/quiz/answer")) {
        return makeSseResponse([
          {
            event: "graded",
            attempt_id: "attempt_1",
            is_correct: true,
            correct_index: 0,
            explanation: "Correct.",
            chip: { chip_type: "document", label: "alpha.txt block1", anchor: "file_alpha#block1/b1" },
            concept_update: { concept_id: "concept_alpha", name: "alpha", state: "touched" },
          },
          {
            event: "quiz_done",
            score: 1,
            total: 1,
            artifact_id: "artifact_3",
            refreshed_starters: [],
          },
        ]);
      }
      if (url.includes("/source/file_alpha/block1%2Fb1") || url.includes("/source/file_alpha/block1/b1")) {
        return makeJsonResponse({
          text: "alpha source text",
          label: "alpha.txt block1",
          file_path: "alpha.txt",
        });
      }
      return new Response("not found", { status: 404 });
    }) as typeof fetch;
  });

  it("streams chat responses", async () => {
    render(<App />);
    fireEvent.change(screen.getByLabelText("Workspace folder"), {
      target: { value: "/tmp/alpha" },
    });
    fireEvent.click(screen.getByText("Index Workspace"));
    await screen.findAllByText("Indexed 1 file.");

    fireEvent.click(screen.getByText("chat"));
    fireEvent.change(screen.getByLabelText("Ask Fieldnotes"), {
      target: { value: "What is alpha?" },
    });
    fireEvent.click(screen.getByText("Send"));

    await screen.findByText(/Grounded answer with citation\./);
    expect(screen.getAllByText("Answer artifact").length).toBeGreaterThan(0);
  });

  it("supports notebook reopening", async () => {
    render(<App />);
    fireEvent.change(screen.getByLabelText("Workspace folder"), {
      target: { value: "/tmp/alpha" },
    });
    fireEvent.click(screen.getByText("Index Workspace"));
    await screen.findAllByText("Indexed 1 file.");

    fireEvent.click(screen.getByText("notebook"));
    await waitFor(() => expect(screen.getAllByText("Answer artifact").length).toBeGreaterThan(0));
    fireEvent.click(screen.getAllByText("Reopen")[0]);
    await screen.findByText("## Explainer");
  });

  it("supports quiz flow", async () => {
    render(<App />);
    fireEvent.change(screen.getByLabelText("Workspace folder"), {
      target: { value: "/tmp/alpha" },
    });
    fireEvent.click(screen.getByText("Index Workspace"));
    await screen.findAllByText("Indexed 1 file.");

    fireEvent.click(screen.getByText("quiz"));
    fireEvent.click(screen.getByText("Start Quiz"));
    await screen.findByText("Which file contains alpha?");
    fireEvent.click(screen.getByText("alpha.txt"));
    await waitFor(() => expect(screen.getAllByText("Correct.").length).toBeGreaterThan(0));
  });

  it("jumps through citations into source viewer", async () => {
    render(<App />);
    fireEvent.change(screen.getByLabelText("Workspace folder"), {
      target: { value: "/tmp/alpha" },
    });
    fireEvent.click(screen.getByText("Index Workspace"));
    await screen.findAllByText("Indexed 1 file.");

    fireEvent.click(screen.getByText("chat"));
    fireEvent.change(screen.getByLabelText("Ask Fieldnotes"), {
      target: { value: "What is alpha?" },
    });
    fireEvent.click(screen.getByText("Send"));
    await screen.findByText(/Grounded answer with citation\./);

    fireEvent.click(screen.getAllByText("alpha.txt block1")[0]);
    await screen.findByText("alpha source text");
  });

  it("switches workspaces from recent list", async () => {
    render(<App />);
    fireEvent.change(screen.getByLabelText("Workspace folder"), {
      target: { value: "/tmp/alpha" },
    });
    fireEvent.click(screen.getByText("Index Workspace"));
    await screen.findAllByText("Indexed 1 file.");

    fireEvent.change(screen.getByLabelText("Workspace folder"), {
      target: { value: "/tmp/beta" },
    });
    fireEvent.click(screen.getByText("Index Workspace"));
    await waitFor(() => {
      expect(screen.getByText("/tmp/alpha")).toBeInTheDocument();
      expect(screen.getByText("/tmp/beta")).toBeInTheDocument();
    });
  });

  it("shows developer panel with imported benchmark summary", async () => {
    render(<App />);
    fireEvent.click(screen.getAllByText("Show Dev")[0]);
    fireEvent.click(screen.getByText("developer"));

    const file = new File(
      [
        JSON.stringify({
          latency_summary: {
            retrieval_latency_ms: { count: 1, min: 1, max: 1, avg: 1 },
          },
          retrieval_metrics: { before: { recall_at_5: 1 }, after: { recall_at_5: 1 } },
          execution_metrics: { execution_success_rate: 1 },
          regression_comparison: { status: "ok" },
        }),
      ],
      "benchmarks.json",
      { type: "application/json" },
    );
    Object.defineProperty(file, "text", {
      value: async () =>
        JSON.stringify({
          latency_summary: {
            retrieval_latency_ms: { count: 1, min: 1, max: 1, avg: 1 },
          },
          retrieval_metrics: { before: { recall_at_5: 1 }, after: { recall_at_5: 1 } },
          execution_metrics: { execution_success_rate: 1 },
          regression_comparison: { status: "ok" },
        }),
    });

    const input = screen.getByLabelText("Load benchmark summary") as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });
    await waitFor(() => expect(screen.getAllByText("retrieval_latency_ms").length).toBeGreaterThan(0));
  });

  it("supports retry and regenerate", async () => {
    render(<App />);
    fireEvent.change(screen.getByLabelText("Workspace folder"), {
      target: { value: "/tmp/alpha" },
    });
    fireEvent.click(screen.getByText("Index Workspace"));
    await screen.findAllByText("Indexed 1 file.");

    fireEvent.click(screen.getByText("chat"));
    fireEvent.change(screen.getByLabelText("Ask Fieldnotes"), {
      target: { value: "What is alpha?" },
    });
    fireEvent.click(screen.getByText("Send"));
    await screen.findByText(/Grounded answer with citation\./);

    fireEvent.click(screen.getByText("Retry Last"));
    await waitFor(() =>
      expect(screen.getAllByText(/Grounded answer with citation\./).length).toBeGreaterThan(1),
    );

    fireEvent.click(screen.getAllByText("Regenerate")[0]);
    await waitFor(() =>
      expect(screen.getAllByText(/Grounded answer with citation\./).length).toBeGreaterThan(2),
    );
  });

  it("exports conversation markdown", async () => {
    render(<App />);
    fireEvent.change(screen.getByLabelText("Workspace folder"), {
      target: { value: "/tmp/alpha" },
    });
    fireEvent.click(screen.getByText("Index Workspace"));
    await screen.findAllByText("Indexed 1 file.");

    fireEvent.click(screen.getByText("chat"));
    fireEvent.change(screen.getByLabelText("Ask Fieldnotes"), {
      target: { value: "What is alpha?" },
    });
    fireEvent.click(screen.getByText("Send"));
    await screen.findByText(/Grounded answer with citation\./);

    fireEvent.click(screen.getByText("Export Markdown"));
    expect(navigator.clipboard.writeText).toHaveBeenCalled();
  });

  it("filters notebook artifacts by search", async () => {
    render(<App />);
    fireEvent.change(screen.getByLabelText("Workspace folder"), {
      target: { value: "/tmp/alpha" },
    });
    fireEvent.click(screen.getByText("Index Workspace"));
    await screen.findAllByText("Indexed 1 file.");

    fireEvent.click(screen.getByText("notebook"));
    fireEvent.change(screen.getByLabelText("Search artifacts"), {
      target: { value: "chart" },
    });
    expect(screen.getAllByText("Chart artifact").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Chart artifact").length).toBeGreaterThan(0);
  });

  it("shows quiz review and incorrect filter control", async () => {
    render(<App />);
    fireEvent.change(screen.getByLabelText("Workspace folder"), {
      target: { value: "/tmp/alpha" },
    });
    fireEvent.click(screen.getByText("Index Workspace"));
    await screen.findAllByText("Indexed 1 file.");

    fireEvent.click(screen.getByText("quiz"));
    fireEvent.click(screen.getByText("Start Quiz"));
    await screen.findByText("Which file contains alpha?");
    fireEvent.click(screen.getByText("alpha.txt"));
    await screen.findByText("Completion summary: 1/1");

    fireEvent.click(screen.getByText("Incorrect Review"));
    expect(screen.getByText("Concept Progress")).toBeInTheDocument();
  });

  it("navigates source citations", async () => {
    render(<App />);
    fireEvent.change(screen.getByLabelText("Workspace folder"), {
      target: { value: "/tmp/alpha" },
    });
    fireEvent.click(screen.getByText("Index Workspace"));
    await screen.findAllByText("Indexed 1 file.");

    fireEvent.click(screen.getByText("chat"));
    fireEvent.change(screen.getByLabelText("Ask Fieldnotes"), {
      target: { value: "What is alpha?" },
    });
    fireEvent.click(screen.getByText("Send"));
    await screen.findByText(/Grounded answer with citation\./);

    fireEvent.click(screen.getAllByText("alpha.txt block1")[0]);
    await screen.findByText("alpha source text");
    expect(screen.getByText(/alpha.txt → alpha.txt block1 → block1\/b1/)).toBeInTheDocument();
  });

  it("supports accessibility shortcuts and cancel control", async () => {
    render(<App />);
    fireEvent.change(screen.getByLabelText("Workspace folder"), {
      target: { value: "/tmp/alpha" },
    });
    fireEvent.click(screen.getByText("Index Workspace"));
    await screen.findAllByText("Indexed 1 file.");

    fireEvent.click(screen.getByText("chat"));
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    expect(screen.getByLabelText("Ask Fieldnotes")).toHaveFocus();
    expect(screen.getAllByText(/Ctrl\/Cmd\+K focus/).length).toBeGreaterThan(0);
  });

  it("shows error state for workspace validation", async () => {
    render(<App />);
    fireEvent.change(screen.getByLabelText("Workspace folder"), {
      target: { value: "relative/path" },
    });
    fireEvent.click(screen.getByText("Index Workspace"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Workspace path must be absolute.");
  });
});
