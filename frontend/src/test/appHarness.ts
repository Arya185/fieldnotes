import { vi } from "vitest";

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

export function installAppFetchMock() {
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
    if (url.endsWith("/health")) {
      return makeJsonResponse({ status: "ok", mode: "fake", version: "1.0.0-beta.1" });
    }
    return new Response("not found", { status: 404 });
  }) as typeof fetch;
}
