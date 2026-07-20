import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

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

  it("shows error state for workspace validation", async () => {
    render(<App />);
    fireEvent.change(screen.getByLabelText("Workspace folder"), { target: { value: "relative/path" } });
    fireEvent.click(screen.getByText("Index Workspace"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Workspace path must be absolute.");
  });
});
