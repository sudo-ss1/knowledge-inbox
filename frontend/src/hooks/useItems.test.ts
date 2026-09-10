import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../api/client";
import type { ItemSummary } from "../types";
import { POLL_INTERVAL_MS, useItems } from "./useItems";

vi.mock("../api/client", () => ({
  api: { listItems: vi.fn() },
  ApiError: class extends Error {},
}));

function item(id: string, status: ItemSummary["status"]): ItemSummary {
  return {
    id,
    type: "note",
    title: id,
    source: null,
    status,
    error: null,
    chunk_count: 1,
    preview: "p",
    created_at: "2026-09-10T00:00:00Z",
  };
}

beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
});

describe("useItems", () => {
  it("loads items on mount", async () => {
    vi.mocked(api.listItems).mockResolvedValue({ items: [item("a", "ready")], next_cursor: null });

    const { result } = renderHook(() => useItems());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.items).toHaveLength(1);
    expect(result.current.hasPending).toBe(false);
  });

  it("polls while an item is pending", async () => {
    vi.mocked(api.listItems).mockResolvedValue({ items: [item("a", "pending")], next_cursor: null });

    const { result } = renderHook(() => useItems());
    await waitFor(() => expect(result.current.hasPending).toBe(true));
    const callsAfterMount = vi.mocked(api.listItems).mock.calls.length;

    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 2);

    expect(vi.mocked(api.listItems).mock.calls.length).toBeGreaterThan(callsAfterMount);
  });

  it("does not poll an idle inbox", async () => {
    vi.mocked(api.listItems).mockResolvedValue({ items: [item("a", "ready")], next_cursor: null });

    const { result } = renderHook(() => useItems());
    await waitFor(() => expect(result.current.loading).toBe(false));
    const callsAfterMount = vi.mocked(api.listItems).mock.calls.length;

    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 3);

    expect(vi.mocked(api.listItems).mock.calls.length).toBe(callsAfterMount);
  });

  it("surfaces a load failure as an error message", async () => {
    vi.mocked(api.listItems).mockRejectedValue(new Error("network down"));

    const { result } = renderHook(() => useItems());

    await waitFor(() => expect(result.current.error).toBe("network down"));
    expect(result.current.loading).toBe(false);
  });
});
