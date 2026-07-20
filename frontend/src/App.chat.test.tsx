import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { installAppFetchMock } from "./test/appHarness";

describe("Fieldnotes frontend chat and workspace flows", () => {
  beforeEach(() => {
    installAppFetchMock();
  });

  it("streams chat responses", async () => {
    render(<App />);
    fireEvent.change(screen.getByLabelText("Workspace folder"), { target: { value: "/tmp/alpha" } });
    fireEvent.click(screen.getByText("Index Workspace"));
    await screen.findAllByText("Indexed 1 file.");
    fireEvent.click(screen.getByText("chat"));
    fireEvent.change(screen.getByLabelText("Ask Fieldnotes"), { target: { value: "What is alpha?" } });
    fireEvent.click(screen.getByText("Send"));
    await screen.findByText(/Grounded answer with citation\./);
    expect(screen.getAllByText("Answer artifact").length).toBeGreaterThan(0);
    expect(screen.getAllByLabelText("Saved to Notebook").length).toBeGreaterThan(0);
  });

  it("supports retry and regenerate", async () => {
    render(<App />);
    fireEvent.change(screen.getByLabelText("Workspace folder"), { target: { value: "/tmp/alpha" } });
    fireEvent.click(screen.getByText("Index Workspace"));
    await screen.findAllByText("Indexed 1 file.");
    fireEvent.click(screen.getByText("chat"));
    fireEvent.change(screen.getByLabelText("Ask Fieldnotes"), { target: { value: "What is alpha?" } });
    fireEvent.click(screen.getByText("Send"));
    await screen.findByText(/Grounded answer with citation\./);
    fireEvent.click(screen.getByText("Retry Last"));
    await waitFor(() => expect(screen.getAllByText(/Grounded answer with citation\./).length).toBeGreaterThan(1));
    fireEvent.click(screen.getAllByText("Regenerate")[0]);
    await waitFor(() => expect(screen.getAllByText(/Grounded answer with citation\./).length).toBeGreaterThan(2));
  });

  it("exports conversation markdown", async () => {
    render(<App />);
    fireEvent.change(screen.getByLabelText("Workspace folder"), { target: { value: "/tmp/alpha" } });
    fireEvent.click(screen.getByText("Index Workspace"));
    await screen.findAllByText("Indexed 1 file.");
    fireEvent.click(screen.getByText("chat"));
    fireEvent.change(screen.getByLabelText("Ask Fieldnotes"), { target: { value: "What is alpha?" } });
    fireEvent.click(screen.getByText("Send"));
    await screen.findByText(/Grounded answer with citation\./);
    fireEvent.click(screen.getByText("Export Markdown"));
    expect(navigator.clipboard.writeText).toHaveBeenCalled();
  });

  it("supports accessibility shortcuts", async () => {
    render(<App />);
    fireEvent.change(screen.getByLabelText("Workspace folder"), { target: { value: "/tmp/alpha" } });
    fireEvent.click(screen.getByText("Index Workspace"));
    await screen.findAllByText("Indexed 1 file.");
    fireEvent.click(screen.getByText("chat"));
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    expect(screen.getByLabelText("Ask Fieldnotes")).toHaveFocus();
    expect(screen.getAllByText(/Ctrl\/Cmd\+K focus/).length).toBeGreaterThan(0);
  });

  it("switches workspaces from recent list", async () => {
    render(<App />);
    fireEvent.change(screen.getByLabelText("Workspace folder"), { target: { value: "/tmp/alpha" } });
    fireEvent.click(screen.getByText("Index Workspace"));
    await screen.findAllByText("Indexed 1 file.");
    fireEvent.change(screen.getByLabelText("Workspace folder"), { target: { value: "/tmp/beta" } });
    fireEvent.click(screen.getByText("Index Workspace"));
    await waitFor(() => {
      expect(screen.getByText("/tmp/alpha")).toBeInTheDocument();
      expect(screen.getByText("/tmp/beta")).toBeInTheDocument();
    });
  });

  it("uses backend notebook count for previously indexed recent workspace", async () => {
    window.localStorage.setItem(
      "fieldnotes.workspaces",
      JSON.stringify([
        {
          workspaceId: "ws_alpha",
          folderPath: "/tmp/alpha",
          title: "alpha",
          lastIndexedAt: "2026-07-20T00:00:00Z",
          status: "ready",
        },
        {
          workspaceId: "ws_beta",
          folderPath: "/tmp/beta",
          title: "beta",
          lastIndexedAt: "2026-07-20T00:00:00Z",
          status: "ready",
        },
      ]),
    );
    window.localStorage.setItem("fieldnotes.indexHistory", JSON.stringify([]));

    render(<App />);

    await screen.findByText("3 docs");
    fireEvent.click(screen.getByText("/tmp/beta"));
    await screen.findByText("7 docs");
    expect(screen.queryByText("0 docs")).not.toBeInTheDocument();
  });

  it("shows hidden-artifacts message in context panel when notebook entries are all hidden", async () => {
    window.localStorage.setItem(
      "fieldnotes.workspaces",
      JSON.stringify([
        {
          workspaceId: "ws_alpha",
          folderPath: "/tmp/alpha",
          title: "alpha",
          lastIndexedAt: "2026-07-20T00:00:00Z",
          status: "ready",
        },
      ]),
    );
    window.localStorage.setItem(
      "fieldnotes.noteOverrides",
      JSON.stringify({
        ws_alpha: {
          hiddenIds: ["artifact_1", "artifact_2"],
          pinnedIds: [],
          renamedTitles: {},
        },
      }),
    );

    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: "Notebook" }));
    await screen.findByText("2 artifact(s) hidden or filtered out.");
    expect(screen.queryByText("No notebook entries yet.")).not.toBeInTheDocument();
  });

  it("clears stale route status when switching tabs", async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/quiz/start")) {
        return new Promise<Response>(() => undefined);
      }
      return originalFetch(input, init);
    }) as typeof fetch;

    render(<App />);
    fireEvent.change(screen.getByLabelText("Workspace folder"), { target: { value: "/tmp/alpha" } });
    fireEvent.click(screen.getByText("Index Workspace"));
    await screen.findAllByText("Indexed 1 file.");

    fireEvent.click(screen.getByText("quiz"));
    fireEvent.click(screen.getByText("Start Quiz"));
    expect((await screen.findAllByText("Generating quiz...")).length).toBeGreaterThan(0);

    fireEvent.click(screen.getByText("chat"));
    await screen.findByText("Ask your workspace");
    expect(screen.getAllByText("Ready.").length).toBeGreaterThan(0);
    expect(screen.queryByText("Generating quiz...")).not.toBeInTheDocument();
  });

  it("shows error state for workspace validation", async () => {
    render(<App />);
    fireEvent.change(screen.getByLabelText("Workspace folder"), { target: { value: "relative/path" } });
    fireEvent.click(screen.getByText("Index Workspace"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Workspace path must be absolute.");
  });
});
