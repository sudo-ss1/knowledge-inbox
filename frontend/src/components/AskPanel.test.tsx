import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import AskPanel from "./AskPanel";

vi.mock("../api/client", () => ({
  api: { ask: vi.fn() },
  ApiError: class extends Error {},
}));

const GROUNDED = {
  answer: "Membership changes trigger it [1].",
  sources: [
    {
      marker: 1,
      item_id: "itm_1",
      chunk_id: "chk_1",
      title: "Kafka Docs",
      source: "https://kafka.test/docs",
      snippet: "A rebalance is triggered when membership changes.",
      score: 0.61,
    },
  ],
  abstained: false,
  timings_ms: { embed: 90, retrieve: 4, llm: 1200 },
};

const ABSTAINED = {
  answer: "I don't have anything saved that answers that.",
  sources: [],
  abstained: true,
  timings_ms: { embed: 88, retrieve: 3, llm: 0 },
};

afterEach(() => vi.clearAllMocks());

describe("AskPanel", () => {
  it("shows the answer and its source card", async () => {
    vi.mocked(api.ask).mockResolvedValue(GROUNDED);
    render(<AskPanel />);

    await userEvent.type(screen.getByLabelText(/question/i), "what triggers a rebalance?");
    await userEvent.click(screen.getByRole("button", { name: /ask/i }));

    await waitFor(() => expect(screen.getByText(/Membership changes trigger it/)).toBeInTheDocument());
    expect(screen.getByText("Kafka Docs")).toBeInTheDocument();
    expect(screen.getByText(/A rebalance is triggered/)).toBeInTheDocument();
  });

  it("renders citation markers as buttons that reference a source", async () => {
    vi.mocked(api.ask).mockResolvedValue(GROUNDED);
    render(<AskPanel />);

    await userEvent.type(screen.getByLabelText(/question/i), "why?");
    await userEvent.click(screen.getByRole("button", { name: /ask/i }));

    const marker = await screen.findByRole("button", { name: "[1]" });
    expect(marker).toHaveAttribute("aria-describedby", "source-1");
  });

  it("presents an abstention as a neutral message, not an error", async () => {
    vi.mocked(api.ask).mockResolvedValue(ABSTAINED);
    render(<AskPanel />);

    await userEvent.type(screen.getByLabelText(/question/i), "something unrelated");
    await userEvent.click(screen.getByRole("button", { name: /ask/i }));

    await waitFor(() =>
      expect(screen.getByText(/don't have anything saved/i)).toBeInTheDocument(),
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows a failure as an alert", async () => {
    vi.mocked(api.ask).mockRejectedValue(new Error("Set OPENAI_API_KEY and restart."));
    render(<AskPanel />);

    await userEvent.type(screen.getByLabelText(/question/i), "a question");
    await userEvent.click(screen.getByRole("button", { name: /ask/i }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/OPENAI_API_KEY/));
  });

  it("reports the latency split", async () => {
    vi.mocked(api.ask).mockResolvedValue(GROUNDED);
    render(<AskPanel />);

    await userEvent.type(screen.getByLabelText(/question/i), "why?");
    await userEvent.click(screen.getByRole("button", { name: /ask/i }));

    await waitFor(() => expect(screen.getByText(/1200 ms/)).toBeInTheDocument());
  });
});
