/**
 * Draft review — the human half of suggestion mode.
 *
 * ARIA proposes; MORICE approves, corrects, or rejects. Corrections are the
 * most valuable outcome, so the edit path is a first-class action rather
 * than buried behind a menu.
 *
 * Nothing here sends. The WhatsApp transport is read-only, so "approve"
 * means "this is good, I'll send it myself" — stated plainly in the UI so
 * the behaviour is never ambiguous.
 */
"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type WaDraft } from "@/lib/api";

export function DraftReview() {
  const [drafts, setDrafts] = useState<WaDraft[]>([]);
  const [editing, setEditing] = useState<Record<string, string>>({});
  const [lessons, setLessons] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  const refresh = useCallback(
    () => api.listDrafts().then(setDrafts).catch((e: Error) => setError(e.message)),
    [],
  );

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 20000);
    return () => clearInterval(timer);
  }, [refresh]);

  async function decide(d: WaDraft, decision: string) {
    setError(null);
    try {
      const final = decision === "edited" ? (editing[d.id] ?? "").trim() : "";
      if (decision === "edited" && !final) return;
      const res = await api.decideDraft(d.id, decision, final);
      setLessons(res.lessons);
      setEditing((prev) => {
        const next = { ...prev };
        delete next[d.id];
        return next;
      });
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function copy(text: string, id: string) {
    await navigator.clipboard.writeText(text);
    setCopied(id);
    setTimeout(() => setCopied(null), 1500);
  }

  if (drafts.length === 0) {
    return (
      <section className="glass mb-6 rounded-xl p-4">
        <h3 className="mb-1 text-sm font-medium">Suggested replies</h3>
        <p className="text-xs text-zinc-500">
          Nothing waiting. ARIA drafts replies for contacts you&apos;ve marked
          trusted, once the mode is at least <em>suggest</em>.
        </p>
      </section>
    );
  }

  return (
    <section className="mb-6">
      <h3 className="mb-2 text-sm font-medium text-zinc-300">
        Suggested replies ({drafts.length})
      </h3>

      {error && <p role="alert" className="mb-2 text-sm text-red-400">{error}</p>}

      {lessons !== null && lessons.length > 0 && (
        <div className="glass mb-3 rounded-xl border-cyan-400/30 p-3">
          <p className="mb-1 text-xs font-medium text-cyan-300">ARIA learned:</p>
          <ul className="space-y-0.5">
            {lessons.map((l, i) => (
              <li key={i} className="text-xs text-zinc-300">• {l}</li>
            ))}
          </ul>
        </div>
      )}

      <ul className="space-y-3">
        {drafts.map((d) => (
          <li key={d.id} className="glass rounded-xl p-4">
            <p className="mb-1 text-xs text-zinc-500">
              {d.contact_name} wrote:
            </p>
            <p className="mb-3 rounded-lg bg-white/[0.04] px-3 py-2 text-sm text-zinc-300">
              {d.incoming}
            </p>

            <p className="mb-1 text-xs text-cyan-400/80">ARIA suggests:</p>
            <textarea
              value={editing[d.id] ?? d.draft}
              onChange={(e) =>
                setEditing((prev) => ({ ...prev, [d.id]: e.target.value }))
              }
              rows={3}
              aria-label={`Suggested reply to ${d.contact_name}`}
              className="mb-2 w-full rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm outline-none focus:border-cyan-500/60"
            />

            <p className="mb-3 text-[11px] text-zinc-600">{d.rationale}</p>

            <div className="flex flex-wrap gap-2">
              <button
                onClick={() => copy(editing[d.id] ?? d.draft, d.id)}
                className="rounded-md bg-cyan-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-cyan-500"
              >
                {copied === d.id ? "Copied ✓" : "Copy"}
              </button>
              {(editing[d.id] ?? d.draft) !== d.draft ? (
                <button
                  onClick={() => decide(d, "edited")}
                  className="rounded-md bg-emerald-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-600"
                >
                  Save my version &amp; teach ARIA
                </button>
              ) : (
                <button
                  onClick={() => decide(d, "approved")}
                  className="rounded-md border border-emerald-600/60 px-3 py-1.5 text-xs text-emerald-300 hover:bg-emerald-600/10"
                >
                  Good as-is
                </button>
              )}
              <button
                onClick={() => decide(d, "rejected")}
                className="rounded-md border border-zinc-700 px-3 py-1.5 text-xs text-zinc-400 hover:border-red-500/50 hover:text-red-400"
              >
                Reject
              </button>
            </div>
          </li>
        ))}
      </ul>

      <p className="mt-3 text-[11px] text-zinc-600">
        ARIA cannot send. Copy the reply and send it yourself — editing it
        first is what teaches her your voice.
      </p>
    </section>
  );
}
