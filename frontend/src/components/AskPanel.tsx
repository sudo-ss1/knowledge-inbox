import { useState } from "react";

import { useAsk } from "../hooks/useAsk";
import SourceCard from "./SourceCard";

const MARKER = /(\[\d+\])/g;

/** Turns "…changed [1]." into text plus a button that points at its source card. */
function renderAnswer(answer: string, markers: number[]) {
  return answer.split(MARKER).map((part, index) => {
    const match = /^\[(\d+)\]$/.exec(part);
    if (!match) return <span key={index}>{part}</span>;

    const marker = Number(match[1]);
    if (!markers.includes(marker)) return <span key={index}>{part}</span>;

    return (
      <button
        key={index}
        type="button"
        aria-describedby={`source-${marker}`}
        onClick={() =>
          document
            .getElementById(`source-${marker}`)
            ?.scrollIntoView({ behavior: "smooth", block: "center" })
        }
        className="mx-0.5 rounded bg-slate-200 px-1 text-xs font-semibold text-slate-700 hover:bg-slate-300"
      >
        {part}
      </button>
    );
  });
}

export default function AskPanel() {
  const [question, setQuestion] = useState("");
  const { ask, result, asking, error } = useAsk();

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    await ask(question);
  }

  return (
    <section className="space-y-4">
      <form onSubmit={submit} className="space-y-3 rounded-lg border border-slate-200 bg-white p-4">
        <label className="block text-sm">
          <span className="text-slate-600">Question</span>
          <textarea
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            rows={3}
            placeholder="What did I save about…?"
            className="mt-1 w-full rounded border border-slate-300 p-2"
          />
        </label>

        <button
          type="submit"
          disabled={asking}
          className="rounded bg-slate-900 px-4 py-2 text-sm text-white disabled:opacity-50"
        >
          {asking ? "Thinking…" : "Ask"}
        </button>
      </form>

      {error && (
        <p role="alert" className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </p>
      )}

      {result && (
        <div className="space-y-3">
          <div
            className={`rounded-lg border p-4 text-sm leading-relaxed ${
              result.abstained
                ? "border-slate-200 bg-slate-50 text-slate-600"
                : "border-slate-200 bg-white text-slate-900"
            }`}
          >
            {result.abstained
              ? result.answer
              : renderAnswer(
                  result.answer,
                  result.sources.map((source) => source.marker),
                )}
          </div>

          {result.sources.length > 0 && (
            <ul className="space-y-2">
              {result.sources.map((source) => (
                <SourceCard key={source.marker} source={source} />
              ))}
            </ul>
          )}

          <p className="text-xs text-slate-400">
            embed {result.timings_ms.embed} ms · retrieve {result.timings_ms.retrieve} ms · model{" "}
            {result.timings_ms.llm} ms
          </p>
        </div>
      )}
    </section>
  );
}
