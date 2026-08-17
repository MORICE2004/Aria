/**
 * Research — ask a question, get an answer with its sources.
 *
 * The scope note is the most important thing on this page. ARIA researches
 * over her OWN corpus: the documents and memories MORICE gave her. She has no
 * web access, and a research tool that lets you assume otherwise is worse than
 * no research tool at all — you would trust an answer drawn from a much smaller
 * world than you thought.
 *
 * Every claim is shown with the evidence behind it. There are no fabricated
 * citations here because citations are not generated: they name real stored
 * items, returned by the search that produced them.
 */
"use client";

import { useEffect, useState } from "react";
import { Search } from "lucide-react";
import { api, type ResearchReport, type ResearchSources } from "@/lib/api";

export default function ResearchPage() {
  const [question, setQuestion] = useState("");
  const [depth, setDepth] = useState(2);
  const [remember, setRemember] = useState(false);
  const [report, setReport] = useState<ResearchReport | null>(null);
  const [sources, setSources] = useState<ResearchSources | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.researchSources().then(setSources).catch(() => setSources(null));
  }, []);

  async function run() {
    if (question.trim().length < 3) return;
    setBusy(true);
    setError(null);
    setReport(null);
    try {
      setReport(await api.research(question.trim(), depth, remember));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl">
      <h2 className="mb-1 text-2xl font-semibold">Research</h2>
      <p className="mb-6 text-sm text-zinc-400">
        ARIA answers from what she actually holds — your documents, notes, and
        remembered facts — and cites each one.
      </p>

      {sources && (
        <section className="glass mb-6 rounded-xl p-4">
          <h3 className="text-xs font-medium text-zinc-300">
            What she can search
          </h3>
          <p className="mt-1 text-xs text-zinc-500">
            <span className="text-emerald-400/80">
              {sources.available.join(", ") || "nothing yet"}
            </span>
            {sources.unavailable.length > 0 && (
              <>
                {" · not available: "}
                <span className="text-amber-400/80">
                  {sources.unavailable.join(", ")}
                </span>
              </>
            )}
          </p>
          <p className="mt-2 text-[11px] text-zinc-600">{sources.note}</p>
        </section>
      )}

      <section className="glass mb-6 rounded-xl p-5">
        <label htmlFor="question" className="block text-xs font-medium text-zinc-300">
          Your question
        </label>
        <textarea
          id="question"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          rows={3}
          placeholder="e.g. what have I written about the Tailscale setup?"
          className="mt-2 w-full rounded-lg bg-black/30 p-3 text-sm text-zinc-200 outline-none ring-1 ring-white/10 focus:ring-cyan-500/40"
        />

        <div className="mt-3 flex flex-wrap items-center gap-4">
          <label className="flex items-center gap-2 text-xs text-zinc-400">
            Depth
            <select
              value={depth}
              onChange={(e) => setDepth(Number(e.target.value))}
              className="rounded-lg bg-black/30 px-2 py-1 text-xs text-zinc-200 outline-none ring-1 ring-white/10"
            >
              <option value={1}>search as asked</option>
              <option value={2}>break it into sub-questions</option>
              <option value={3}>go deeper</option>
            </select>
          </label>
          <label className="flex items-center gap-2 text-xs text-zinc-400">
            <input
              type="checkbox"
              checked={remember}
              onChange={(e) => setRemember(e.target.checked)}
              className="accent-cyan-500"
            />
            Remember the findings
          </label>
          <button
            onClick={run}
            disabled={busy || question.trim().length < 3}
            className="ml-auto flex items-center gap-2 rounded-lg bg-cyan-600 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-500 disabled:opacity-40"
          >
            <Search size={14} aria-hidden />
            {busy ? "Researching…" : "Research"}
          </button>
        </div>
      </section>

      {error && (
        <p role="alert" className="mb-4 text-sm text-red-400">
          {error}
        </p>
      )}

      {report && (
        <>
          <section className="glass mb-4 rounded-xl p-5">
            <p className="whitespace-pre-wrap text-sm text-zinc-100">
              {report.answer}
            </p>
            <p className="mt-3 border-t border-white/10 pt-3 text-[11px] text-zinc-500">
              {report.scope_note}
            </p>
            <p className="mt-1 text-[11px] text-zinc-600">
              searched {report.sources_searched.join(", ") || "nothing"} ·
              answered by {report.ran_on}
              {report.remembered && " · saved to memory"}
            </p>
          </section>

          {report.sub_questions.length > 0 && (
            <section className="mb-4">
              <h3 className="mb-2 text-sm font-medium text-zinc-300">
                What she looked into
              </h3>
              <ul className="space-y-1">
                {report.sub_questions.map((q, i) => (
                  <li key={i} className="text-xs text-zinc-500">
                    • {q}
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section>
            <h3 className="mb-2 text-sm font-medium text-zinc-300">
              Evidence ({report.evidence.length})
            </h3>
            {report.evidence.length === 0 ? (
              <p className="text-xs text-zinc-500">
                Nothing in your own material was relevant. That is the honest
                answer, not a failure — add a document and ask again.
              </p>
            ) : (
              <ul className="space-y-2">
                {report.evidence.map((item, i) => (
                  <li key={`${item.reference_id}-${i}`} className="glass rounded-xl p-3">
                    <p className="text-xs font-medium text-cyan-300/90">
                      {item.citation}
                    </p>
                    <p className="mt-1 whitespace-pre-wrap text-xs text-zinc-400">
                      {item.content}
                    </p>
                    <p className="mt-1 text-[11px] text-zinc-600">
                      {item.source} · match {item.score.toFixed(2)}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </div>
  );
}
