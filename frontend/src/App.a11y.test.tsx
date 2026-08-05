import axe from "axe-core";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import App from "./App";
import { installAppFetchMock } from "./test/appHarness";

// jsdom has no real layout/paint engine, so color-contrast and a few other
// visual-only rules cannot be evaluated meaningfully here; contrast is
// verified manually instead (see docs/design.md section 10). Everything
// else — labels, roles, keyboard-operable names, aria-* validity — axe can
// check accurately against the rendered DOM.
const AXE_OPTIONS: axe.RunOptions = {
  rules: {
    "color-contrast": { enabled: false },
  },
};

async function runAxe() {
  const results = await axe.run(document.body, AXE_OPTIONS);
  expect(results.violations).toEqual([]);
}

describe("Fieldnotes accessibility", () => {
  beforeEach(() => {
    installAppFetchMock();
  });

  it("workspace view has no axe violations", async () => {
    render(<App />);
    fireEvent.change(screen.getByLabelText("Workspace folder"), { target: { value: "/tmp/alpha" } });
    fireEvent.click(screen.getByText("Index Workspace"));
    await screen.findAllByText("Indexed 1 file.");
    await runAxe();
  });

  it("chat view with a grounded answer has no axe violations", async () => {
    render(<App />);
    fireEvent.change(screen.getByLabelText("Workspace folder"), { target: { value: "/tmp/alpha" } });
    fireEvent.click(screen.getByText("Index Workspace"));
    await screen.findAllByText("Indexed 1 file.");
    fireEvent.click(screen.getByText("chat"));
    fireEvent.change(screen.getByLabelText("Ask Fieldnotes"), { target: { value: "What is alpha?" } });
    fireEvent.click(screen.getByText("Send"));
    await screen.findByText(/Grounded answer with citation\./);
    await runAxe();
  });

  it("quiz view has no axe violations", async () => {
    render(<App />);
    fireEvent.change(screen.getByLabelText("Workspace folder"), { target: { value: "/tmp/alpha" } });
    fireEvent.click(screen.getByText("Index Workspace"));
    await screen.findAllByText("Indexed 1 file.");
    fireEvent.click(screen.getByText("quiz"));
    fireEvent.click(screen.getByText("Start Quiz"));
    await screen.findByText("Which file contains alpha?");
    await runAxe();
  });

  it("notebook view has no axe violations", async () => {
    render(<App />);
    fireEvent.change(screen.getByLabelText("Workspace folder"), { target: { value: "/tmp/alpha" } });
    fireEvent.click(screen.getByText("Index Workspace"));
    await screen.findAllByText("Indexed 1 file.");
    fireEvent.click(screen.getByText("notebook"));
    await screen.findAllByText("Answer artifact");
    await runAxe();
  });
});
