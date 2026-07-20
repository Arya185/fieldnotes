import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import App from "./App";
import { installAppFetchMock } from "./test/appHarness";

describe("Fieldnotes frontend developer diagnostics", () => {
  beforeEach(() => {
    installAppFetchMock();
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
});
