export type ItemStatus = "pending" | "ready" | "failed";

export interface ItemSummary {
  id: string;
  type: "note" | "url";
  title: string | null;
  source: string | null;
  status: ItemStatus;
  error: string | null;
  chunk_count: number;
  preview: string;
  created_at: string;
}

export interface ItemsPage {
  items: ItemSummary[];
  next_cursor: string | null;
}

export interface IngestAccepted {
  id: string;
  type: string;
  status: ItemStatus;
  created_at: string;
}

export interface QuerySource {
  marker: number;
  item_id: string;
  chunk_id: string;
  title: string | null;
  source: string | null;
  snippet: string;
  score: number;
}

export interface QueryResponse {
  answer: string;
  sources: QuerySource[];
  abstained: boolean;
  timings_ms: Record<string, number>;
}
