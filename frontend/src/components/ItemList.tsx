import type { ItemSummary } from "../types";
import StatusPill from "./StatusPill";

interface Props {
  items: ItemSummary[];
  loading: boolean;
  error: string | null;
}

export default function ItemList({ items, loading, error }: Props) {
  if (error)
    return (
      <p role="alert" className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
        {error}
      </p>
    );

  if (loading) return <p className="text-sm text-slate-500">Loading…</p>;

  if (items.length === 0)
    return <p className="text-sm text-slate-500">Nothing saved yet. Add a note or a URL above.</p>;

  return (
    <ul className="space-y-2">
      {items.map((item) => (
        <li key={item.id} className="rounded-lg border border-slate-200 bg-white p-3">
          <div className="flex items-start justify-between gap-2">
            <h3 className="text-sm font-medium text-slate-900">{item.title ?? "Untitled"}</h3>
            <StatusPill status={item.status} />
          </div>

          {item.source && (
            <a
              href={item.source}
              target="_blank"
              rel="noreferrer"
              className="mt-1 block truncate text-xs text-blue-700 hover:underline"
            >
              {item.source}
            </a>
          )}

          {item.preview && <p className="mt-2 text-sm text-slate-600">{item.preview}</p>}

          {/* A failure the user cannot see is a failure they cannot act on. */}
          {item.error && <p className="mt-2 text-sm text-red-700">{item.error}</p>}

          {item.status === "ready" && (
            <p className="mt-2 text-xs text-slate-400">{item.chunk_count} chunks indexed</p>
          )}
        </li>
      ))}
    </ul>
  );
}
