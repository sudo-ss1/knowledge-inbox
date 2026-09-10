import type { IngestAccepted, ItemsPage, QueryResponse } from "../types";

const BASE = import.meta.env.VITE_API_BASE ?? "";

export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public requestId?: string,
    public status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });

  const raw = await response.text();

  let body: unknown = null;
  if (raw) {
    try {
      body = JSON.parse(raw);
    } catch {
      // A non-JSON body means something upstream of the API answered — most often
      // the dev proxy when the backend isn't running.
      throw new ApiError(
        "unreadable_response",
        `Could not read the server's response (HTTP ${response.status}). Is the API running?`,
        undefined,
        response.status,
      );
    }
  }

  if (!response.ok) {
    const envelope = (body as { error?: { code?: string; message?: string; request_id?: string } } | null)?.error;
    throw new ApiError(
      envelope?.code ?? "unknown_error",
      envelope?.message ?? `Request failed with status ${response.status}.`,
      envelope?.request_id,
      response.status,
    );
  }

  return body as T;
}

export const api = {
  ingestNote: (content: string) =>
    request<IngestAccepted>("/ingest", {
      method: "POST",
      body: JSON.stringify({ type: "note", content }),
    }),

  ingestUrl: (url: string) =>
    request<IngestAccepted>("/ingest", {
      method: "POST",
      body: JSON.stringify({ type: "url", url }),
    }),

  listItems: () => request<ItemsPage>("/items"),

  ask: (question: string) =>
    request<QueryResponse>("/query", {
      method: "POST",
      body: JSON.stringify({ question }),
    }),
};
