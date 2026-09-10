import { useState } from "react";

import { api } from "../api/client";

type Mode = "note" | "url";

export default function AddItemForm({ onAdded }: { onAdded: () => void }) {
  const [mode, setMode] = useState<Mode>("note");
  const [value, setValue] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function validate(): string | null {
    const trimmed = value.trim();
    if (!trimmed) return mode === "note" ? "A note cannot be empty." : "A URL cannot be empty.";
    if (mode === "url" && !/^https?:\/\/\S+$/i.test(trimmed))
      return "That needs to be an http or https URL.";
    return null;
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const invalid = validate();
    if (invalid) {
      setProblem(invalid);
      return;
    }

    setSaving(true);
    setProblem(null);
    try {
      const trimmed = value.trim();
      if (mode === "note") await api.ingestNote(trimmed);
      else await api.ingestUrl(trimmed);
      setValue("");
      onAdded();
    } catch (cause) {
      setProblem(cause instanceof Error ? cause.message : "Could not save that.");
    } finally {
      setSaving(false);
    }
  }

  function switchTo(next: Mode) {
    setMode(next);
    setValue("");
    setProblem(null);
  }

  return (
    <form onSubmit={submit} className="space-y-3 rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex gap-1 text-sm">
        {(["note", "url"] as Mode[]).map((option) => (
          <button
            key={option}
            type="button"
            aria-pressed={mode === option}
            onClick={() => switchTo(option)}
            className={`rounded px-3 py-1 capitalize ${
              mode === option ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-700"
            }`}
          >
            {option}
          </button>
        ))}
      </div>

      {mode === "note" ? (
        <label className="block text-sm">
          <span className="text-slate-600">Note</span>
          <textarea
            value={value}
            onChange={(event) => setValue(event.target.value)}
            rows={4}
            placeholder="Something worth remembering…"
            className="mt-1 w-full rounded border border-slate-300 p-2 font-normal"
          />
        </label>
      ) : (
        <label className="block text-sm">
          <span className="text-slate-600">URL</span>
          <input
            type="text"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            placeholder="https://example.com/article"
            className="mt-1 w-full rounded border border-slate-300 p-2"
          />
        </label>
      )}

      {problem && (
        <p role="alert" className="text-sm text-red-700">
          {problem}
        </p>
      )}

      <button
        type="submit"
        disabled={saving}
        className="rounded bg-slate-900 px-4 py-2 text-sm text-white disabled:opacity-50"
      >
        {saving ? "Saving…" : "Save"}
      </button>
    </form>
  );
}
