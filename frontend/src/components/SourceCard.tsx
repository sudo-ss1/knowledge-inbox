import type { QuerySource } from "../types";

export default function SourceCard({ source }: { source: QuerySource }) {
  return (
    <li id={`source-${source.marker}`} className="rounded-lg border border-slate-200 bg-white p-3">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-xs font-semibold text-slate-500">[{source.marker}]</span>
        <span className="text-xs text-slate-400">score {source.score.toFixed(3)}</span>
      </div>

      <h4 className="mt-1 text-sm font-medium text-slate-900">{source.title ?? "Untitled"}</h4>

      {source.source && (
        <a
          href={source.source}
          target="_blank"
          rel="noreferrer"
          className="block truncate text-xs text-blue-700 hover:underline"
        >
          {source.source}
        </a>
      )}

      <p className="mt-2 text-sm text-slate-600">{source.snippet}</p>
    </li>
  );
}
