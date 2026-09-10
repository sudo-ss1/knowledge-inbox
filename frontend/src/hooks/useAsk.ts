import { useCallback, useState } from "react";

import { api } from "../api/client";
import type { QueryResponse } from "../types";

export function useAsk() {
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const ask = useCallback(async (question: string) => {
    if (!question.trim()) return;

    setAsking(true);
    setError(null);
    try {
      setResult(await api.ask(question.trim()));
    } catch (cause) {
      setResult(null);
      setError(cause instanceof Error ? cause.message : "Could not answer that.");
    } finally {
      setAsking(false);
    }
  }, []);

  const reset = useCallback(() => {
    setResult(null);
    setError(null);
  }, []);

  return { ask, result, asking, error, reset };
}
