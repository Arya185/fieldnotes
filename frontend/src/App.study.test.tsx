import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import App from "./App";
import { installAppFetchMock } from "./test/appHarness";

describe("Fieldnotes frontend notebook, quiz, and source flows", () => {
  beforeEach(() => {
    installAppFetchMock();
  });

  it("supports notebook reopening", async () => {
    render(<App />);
    fireEvent.change(screen.getByLabelText("Workspace folder"), { target: { value: "/tmp/alpha" } });
    fireEvent.click(screen.getByText("Index Workspace"));
    await screen.findAllByText("Indexed 1 file.");
    fireEvent.click(screen.getByText("notebook"));
    await waitFor(() => expect(screen.getAllByText("Answer artifact").length).toBeGreaterThan(0));
    fireEvent.click(screen.getAllByText("Reopen")[0]);
    await screen.findByText("## Explainer");
  });

  it("filters notebook artifacts by search", async () => {
    render(<App />);
    fireEvent.change(screen.getByLabelText("Workspace folder"), { target: { value: "/tmp/alpha" } });
    fireEvent.click(screen.getByText("Index Workspace"));
    await screen.findAllByText("Indexed 1 file.");
    fireEvent.click(screen.getByText("notebook"));
    fireEvent.change(screen.getByLabelText("Search artifacts"), { target: { value: "chart" } });
    expect(screen.getAllByText("Chart artifact").length).toBeGreaterThan(0);
  });

  it("supports quiz flow", async () => {
    render(<App />);
    fireEvent.change(screen.getByLabelText("Workspace folder"), { target: { value: "/tmp/alpha" } });
    fireEvent.click(screen.getByText("Index Workspace"));
    await screen.findAllByText("Indexed 1 file.");
    fireEvent.click(screen.getByText("quiz"));
    fireEvent.click(screen.getByText("Start Quiz"));
    await screen.findByText("Which file contains alpha?");
    fireEvent.click(screen.getByText("alpha.txt"));
    await waitFor(() => expect(screen.getAllByText("Correct.").length).toBeGreaterThan(0));
  });

  it("shows quiz review and incorrect filter control", async () => {
    render(<App />);
    fireEvent.change(screen.getByLabelText("Workspace folder"), { target: { value: "/tmp/alpha" } });
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

  it("jumps through citations into source viewer", async () => {
    render(<App />);
    fireEvent.change(screen.getByLabelText("Workspace folder"), { target: { value: "/tmp/alpha" } });
    fireEvent.click(screen.getByText("Index Workspace"));
    await screen.findAllByText("Indexed 1 file.");
    fireEvent.click(screen.getByText("chat"));
    fireEvent.change(screen.getByLabelText("Ask Fieldnotes"), { target: { value: "What is alpha?" } });
    fireEvent.click(screen.getByText("Send"));
    await screen.findByText(/Grounded answer with citation\./);
    fireEvent.click(screen.getAllByText("alpha.txt block1")[0]);
    await screen.findByText("alpha source text");
  });

  it("navigates source citations", async () => {
    render(<App />);
    fireEvent.change(screen.getByLabelText("Workspace folder"), { target: { value: "/tmp/alpha" } });
    fireEvent.click(screen.getByText("Index Workspace"));
    await screen.findAllByText("Indexed 1 file.");
    fireEvent.click(screen.getByText("chat"));
    fireEvent.change(screen.getByLabelText("Ask Fieldnotes"), { target: { value: "What is alpha?" } });
    fireEvent.click(screen.getByText("Send"));
    await screen.findByText(/Grounded answer with citation\./);
    fireEvent.click(screen.getAllByText("alpha.txt block1")[0]);
    await screen.findByText("alpha source text");
    expect(screen.getByText(/alpha.txt → alpha.txt block1 → block1\/b1/)).toBeInTheDocument();
  });

  it("shows a non-ready empty workspace state when indexing produces zero chunks", async () => {
    render(<App />);
    fireEvent.change(screen.getByLabelText("Workspace folder"), { target: { value: "/tmp/empty" } });
    fireEvent.click(screen.getByText("Index Workspace"));
    await screen.findAllByText("Workspace indexed, but no supported content produced searchable chunks.");
    expect(screen.getAllByText("0 files indexed").length).toBeGreaterThan(0);
    expect(
      screen.getByText(/No searchable content found\. Check folder path and supported file types:/),
    ).toBeInTheDocument();
  });
});
