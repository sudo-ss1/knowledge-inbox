import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import type { ItemSummary } from "../types";

export const POLL_INTERVAL_MS = 2000;

export function useItems() {
  const [items, setItems] = useState<ItemSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const page = await api.listItems();
      setItems(page.items);
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load your items.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const hasPending = items.some((item) => item.status === "pending");

  // Poll only while something is actually being indexed. An idle inbox that
  // keeps refetching is waste that shows up in the network tab.
  useEffect(() => {
    if (!hasPending) return;
    const timer = setInterval(() => void refresh(), POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [hasPending, refresh]);

  return { items, loading, error, refresh, hasPending };
}
