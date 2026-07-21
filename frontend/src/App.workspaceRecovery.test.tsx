import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import App from "./App";
import { installAppFetchMock, makeErrorJsonResponse } from "./test/appHarness";

describe("Fieldnotes stale workspace recovery", () => {
  beforeEach(() => {
    installAppFetchMock();
    window.sessionStorage.clear();
  });

  it("removes stale workspace and shows recovery banner", async () => {
    window.localStorage.setItem(
      "fieldnotes.workspaces",
      JSON.stringify([
        { workspaceId: "ws_stale", folderPath: "/tmp/stale", title: "stale", lastIndexedAt: "2026-07-20T00:00:00Z", status: "ready" },
      ]),
    );

    const originalFetch = globalThis.fetch;
    globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/notebook?workspace_id=ws_stale")) {
        return makeErrorJsonResponse(404, { code: "WORKSPACE_NOT_FOUND", message: "Selected workspace was not found." });
      }
      return originalFetch(input, init);
    }) as typeof fetch;

    render(<App />);

    await screen.findByRole("status");
    expect(screen.getByRole("status")).toHaveTextContent(
      "This workspace is no longer available. It may have been moved or deleted. Please select another workspace or index a new folder.",
    );
    expect(window.localStorage.getItem("fieldnotes.workspaces")).toBe("[]");
    expect(screen.getByText("Choose a workspace")).toBeInTheDocument();
  });

  it("switches to remaining valid workspace automatically", async () => {
    window.localStorage.setItem(
      "fieldnotes.workspaces",
      JSON.stringify([
        { workspaceId: "ws_stale", folderPath: "/tmp/stale", title: "stale", lastIndexedAt: "2026-07-20T00:00:00Z", status: "ready" },
        { workspaceId: "ws_beta", folderPath: "/tmp/beta", title: "beta", lastIndexedAt: "2026-07-20T00:00:00Z", status: "ready" },
      ]),
    );

    const originalFetch = globalThis.fetch;
    globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/notebook?workspace_id=ws_stale")) {
        return makeErrorJsonResponse(404, { code: "WORKSPACE_NOT_FOUND", message: "Selected workspace was not found." });
      }
      return originalFetch(input, init);
    }) as typeof fetch;

    render(<App />);

    await screen.findByRole("status");
    expect(screen.getByRole("status")).toHaveTextContent(
      "This workspace is no longer available. It may have been moved or deleted. Please select another workspace or index a new folder.",
    );
    await screen.findByText("Folder: /tmp/beta");
    await screen.findByText("7 indexed documents");
    expect(window.localStorage.getItem("fieldnotes.workspaces")).not.toContain("ws_stale");
  });

  it("returns to workspace screen when only workspace is deleted", async () => {
    window.localStorage.setItem(
      "fieldnotes.workspaces",
      JSON.stringify([
        { workspaceId: "ws_stale", folderPath: "/tmp/stale", title: "stale", lastIndexedAt: "2026-07-20T00:00:00Z", status: "ready" },
      ]),
    );
    window.location.hash = "#chat";

    const originalFetch = globalThis.fetch;
    globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/notebook?workspace_id=ws_stale")) {
        return makeErrorJsonResponse(404, { code: "WORKSPACE_NOT_FOUND", message: "Selected workspace was not found." });
      }
      return originalFetch(input, init);
    }) as typeof fetch;

    render(<App />);

    await screen.findByText("Choose a workspace");
    expect(screen.getByText("Index Workspace")).toBeInTheDocument();
  });

  it("keeps existing handling for DATABASE_ERROR", async () => {
    window.localStorage.setItem(
      "fieldnotes.workspaces",
      JSON.stringify([
        { workspaceId: "ws_alpha", folderPath: "/tmp/alpha", title: "alpha", lastIndexedAt: "2026-07-20T00:00:00Z", status: "ready" },
      ]),
    );

    globalThis.fetch = (async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/health")) {
        return new Response(JSON.stringify({ status: "ok", mode: "fake", version: "1.0.0-beta.1" }), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url.includes("/notebook?workspace_id=ws_alpha")) {
        return makeErrorJsonResponse(500, { code: "DATABASE_ERROR", message: "Workspace data is unavailable right now." });
      }
      return new Response("not found", { status: 404 });
    }) as typeof fetch;

    render(<App />);

    await screen.findByRole("alert");
    expect(screen.getByRole("alert")).toHaveTextContent("Notebook load failed: Workspace data is unavailable right now.");
    expect(window.localStorage.getItem("fieldnotes.workspaces")).toContain("ws_alpha");
  });

  it("does not clear cache for generic 500 errors", async () => {
    window.localStorage.setItem(
      "fieldnotes.workspaces",
      JSON.stringify([
        { workspaceId: "ws_alpha", folderPath: "/tmp/alpha", title: "alpha", lastIndexedAt: "2026-07-20T00:00:00Z", status: "ready" },
      ]),
    );

    globalThis.fetch = (async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/health")) {
        return new Response(JSON.stringify({ status: "ok", mode: "fake", version: "1.0.0-beta.1" }), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url.includes("/notebook?workspace_id=ws_alpha")) {
        return new Response("server exploded", { status: 500 });
      }
      return new Response("not found", { status: 404 });
    }) as typeof fetch;

    render(<App />);

    await screen.findByRole("alert");
    expect(screen.getByRole("alert")).toHaveTextContent("Notebook load failed: 500");
    expect(window.localStorage.getItem("fieldnotes.workspaces")).toContain("ws_alpha");
  });
});
