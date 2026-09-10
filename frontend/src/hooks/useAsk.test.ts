import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import { useAsk } from "./useAsk";

vi.mock("../api/client", () => ({
  api: { ask: vi.fn() },
  ApiError: class extends Error {},
}));

const ANSWER = {
  answer: "Membership changes trigger it [1].",
  sources: [
    {
      marker: 1,
      item_id: "itm_1",
      chunk_id: "chk_1",
      title: "Kafka",
      source: null,
      snippet: "A rebalance is triggered…",
      score: 0.61,
    },
  ],
  abstained: false,
  timings_ms: { embed: 90, retrieve: 4, llm: 1200 },
};

afterEach(() => vi.clearAllMocks());

describe("useAsk", () => {
  it("stores the answer on success", async () => {
    vi.mocked(api.ask).mockResolvedValue(ANSWER);
    const { result } = renderHook(() => useAsk());

    await act(async () => await result.current.ask("what triggers a rebalance?"));

    await waitFor(() => expect(result.current.result?.answer).toBe(ANSWER.answer));
    expect(result.current.asking).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it("ignores a blank question", async () => {
    const { result } = renderHook(() => useAsk());

    await act(async () => await result.current.ask("   "));

    expect(api.ask).not.toHaveBeenCalled();
  });

  it("records a failure message", async () => {
    vi.mocked(api.ask).mockRejectedValue(new Error("Set OPENAI_API_KEY and restart."));
    const { result } = renderHook(() => useAsk());

    await act(async () => await result.current.ask("a question"));

    await waitFor(() => expect(result.current.error).toMatch(/OPENAI_API_KEY/));
    expect(result.current.result).toBeNull();
  });

  it("reset clears the previous answer", async () => {
    vi.mocked(api.ask).mockResolvedValue(ANSWER);
    const { result } = renderHook(() => useAsk());
    await act(async () => await result.current.ask("q"));
    await waitFor(() => expect(result.current.result).not.toBeNull());

    act(() => result.current.reset());

    expect(result.current.result).toBeNull();
  });
});
