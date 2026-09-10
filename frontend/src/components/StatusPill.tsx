import type { ItemStatus } from "../types";

const STYLES: Record<ItemStatus, string> = {
  pending: "bg-amber-100 text-amber-800",
  ready: "bg-emerald-100 text-emerald-800",
  failed: "bg-red-100 text-red-800",
};

const LABELS: Record<ItemStatus, string> = {
  pending: "Indexing",
  ready: "Ready",
  failed: "Failed",
};

export default function StatusPill({ status }: { status: ItemStatus }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STYLES[status]}`}>
      {LABELS[status]}
      {status === "pending" && <span className="ml-1 animate-pulse">…</span>}
    </span>
  );
}
