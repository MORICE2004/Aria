/**
 * Memory viewer — see, add, search, and delete everything ARIA remembers.
 *
 * Privacy by default: nothing here is hidden. If you delete a memory it is
 * gone from the database, embeddings included, immediately.
 */
"use client";

import { useEffect, useState } from "react";
import { api, type MemoryHit, type MemoryItem } from "@/lib/api";

const KINDS = ["note", "document", "fact", "style"] as const;

export default function MemoryPage() {
  const [items, setItems] = useState<MemoryItem[]>([]);
  const [hits, setHits] = useState<MemoryHit[] | null>(null); // null = not searching
  const [query, setQuery] = useState("");
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [kind, setKind] = useState<(typeof KINDS)[number]>("note");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = () =>
    api.listMemories().then(setItems).catch((e: Error) => setError(e.message));

  useEffect(() => {
    refresh();
  }, []);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim() || !content.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await api.addMemory({ title: title.trim(), content: content.trim(), kind });
      setTitle("");
      setContent("");
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function search(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) {
      setHits(null);
      return;
    }
    try {
      setHits(await api.searchMemories(query.trim()));
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function remove(id: string) {
    // Deleting a memory is permanent — confirm with the user first.
    if (!window.confirm("Delete this memory permanently?")) return;
    await api.deleteMemory(id);
    setHits(null);
    await refresh();
  }

  return (
    <div className="mx-auto max-w-3xl">
      <h2 className="mb-1 text-2xl font-semibold">Memory</h2>
      <p className="mb-6 text-sm text-zinc-400">
        Everything ARIA knows about you, in one inspectable place. Chat uses
        these memories automatically when they are relevant.
      </p>

      {error && (
        <p role="alert" className="mb-4 text-xs text-red-400">
          {error}
        </p>
      )}

      {/* Add a memory */}
      <form
        onSubmit={add}
        className="mb-6 space-y-2 glass rounded-xl p-4"
      >
        <div className="flex gap-2">
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Title (e.g. 'My career goals')"
            aria-label="Memory title"
            className="flex-1 rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm outline-none focus:border-zinc-500"
          />
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value as (typeof KINDS)[number])}
            aria-label="Memory kind"
            className="rounded-md border border-zinc-700 bg-zinc-950 px-2 py-2 text-sm"
          >
            {KINDS.map((k) => (
              <option key={k}>{k}</option>
            ))}
          </select>
        </div>
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder="Content — paste a note, a document, a fact about you, or a writing sample…"
          aria-label="Memory content"
          rows={4}
          className="w-full rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm outline-none focus:border-zinc-500"
        />
        <button
          type="submit"
          disabled={busy || !title.trim() || !content.trim()}
          className="rounded-md bg-cyan-600 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-500 disabled:opacity-40"
        >
          {busy ? "Saving…" : "Remember this"}
        </button>
      </form>

      {/* Semantic search */}
      <form onSubmit={search} className="mb-4 flex gap-2">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by meaning, e.g. 'what are my goals?'"
          aria-label="Search memories"
          className="flex-1 rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm outline-none focus:border-zinc-500"
        />
        <button className="rounded-md bg-zinc-100 px-4 py-2 text-sm font-medium text-zinc-900 hover:bg-white">
          Search
        </button>
        {hits !== null && (
          <button
            type="button"
            onClick={() => setHits(null)}
            className="rounded-md border border-zinc-700 px-3 py-2 text-sm text-zinc-400 hover:text-white"
          >
            Clear
          </button>
        )}
      </form>

      {/* Results / list */}
      <ul className="space-y-2">
        {(hits ?? items).map((m) => (
          <li
            key={hits ? `${(m as MemoryHit).item_id}-${m.content.slice(0, 16)}` : m.id}
            className="glass rounded-xl p-4"
          >
            <div className="mb-1 flex items-center justify-between">
              <span className="text-sm font-medium">
                {m.title}{" "}
                <span className="ml-2 rounded bg-white/10 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-zinc-400">
                  {m.kind}
                </span>
                {hits && (
                  <span className="ml-2 text-xs text-zinc-500">
                    match {(m as MemoryHit).score.toFixed(2)}
                  </span>
                )}
              </span>
              <button
                onClick={() => remove(hits ? (m as MemoryHit).item_id : m.id)}
                className="text-xs text-zinc-500 hover:text-red-400"
              >
                Delete
              </button>
            </div>
            <p className="whitespace-pre-wrap text-sm text-zinc-400">
              {m.content.length > 400 ? m.content.slice(0, 400) + "…" : m.content}
            </p>
          </li>
        ))}
        {(hits ?? items).length === 0 && (
          <p className="text-sm text-zinc-500">
            {hits ? "No matches." : "Nothing remembered yet — add your first memory above."}
          </p>
        )}
      </ul>
    </div>
  );
}
