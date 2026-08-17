/**
 * Communication Profile — what ARIA has learned about how you write.
 *
 * Four principles made visible:
 *   • every pattern shows its evidence and confidence
 *   • nothing is learned silently — you can preview a lesson before it sticks
 *   • anything wrong can be deleted
 *   • ARIA holds one voice per audience, and you can see which is which
 */
"use client";

import { useCallback, useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { api, type StyleProfile, type VoiceReadiness } from "@/lib/api";

/** Audiences you can label a paste with. Free text is allowed by the API;
 *  these are the ones worth suggesting. */
const RELATIONSHIPS = [
  "friend",
  "family",
  "partner",
  "colleague",
  "boss",
  "client",
  "recruiter",
  "academic",
] as const;

function confidenceColor(c: number): string {
  if (c >= 0.6) return "text-emerald-400";
  if (c >= 0.25) return "text-amber-400";
  return "text-zinc-500";
}

function confidenceLabel(c: number): string {
  if (c >= 0.6) return "confident";
  if (c >= 0.25) return "tentative";
  return "too weak to use";
}

export default function StylePage() {
  const [profile, setProfile] = useState<StyleProfile | null>(null);
  const [rule, setRule] = useState("");
  const [draft, setDraft] = useState("");
  const [final, setFinal] = useState("");
  const [lessons, setLessons] = useState<string[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [samples, setSamples] = useState("");
  const [sampleAudience, setSampleAudience] = useState("");
  const [readiness, setReadiness] = useState<VoiceReadiness | null>(null);
  const [viewScope, setViewScope] = useState<string>("");

  const refresh = useCallback(
    () =>
      Promise.all([
        api.getStyleProfile(viewScope ? { scope: viewScope } : {}),
        api.voiceReadiness(),
      ])
        .then(([p, r]) => {
          setProfile(p);
          setReadiness(r);
        })
        .catch((e: Error) => setError(e.message)),
    [viewScope],
  );

  useEffect(() => {
    const first = setTimeout(refresh, 0);
    return () => clearTimeout(first);
  }, [refresh]);

  async function addSamples() {
    if (!samples.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.addStyleSamples(
        samples,
        sampleAudience ? `pasted messages (${sampleAudience})` : "pasted messages",
        sampleAudience || undefined,
      );
      setSamples("");
      setNote(`Learned from ${r.added} of your messages. ${r.note}`);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function relearn() {
    setBusy(true);
    setError(null);
    try {
      const r = await api.refreshAllStyleScopes();
      setNote(
        r.scopes.length
          ? `Re-measured ${r.scopes.length} layer${r.scopes.length === 1 ? "" : "s"}: ` +
            r.scopes
              .map((s) => `${s.description} (${s.samples})`)
              .join(", ") +
            `. Audiences with fewer than ${r.minimum_samples_per_scope} of your messages are left unmeasured rather than guessed.`
          : "No messages you wrote yet — ARIA learns your voice from your own outgoing messages.",
      );
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function teach(e: React.FormEvent) {
    e.preventDefault();
    if (!rule.trim()) return;
    await api.addStyleRule(rule.trim());
    setRule("");
    setNote("Rule saved — ARIA will always follow it.");
    await refresh();
  }

  async function preview() {
    if (!draft.trim() || !final.trim()) return;
    const r = await api.previewLessons(draft, final);
    setLessons(r.lessons);
  }

  async function commitLesson() {
    if (!draft.trim() || !final.trim()) return;
    const r = await api.recordStyleFeedback("edited", draft, final);
    setLessons(r.lessons);
    setNote("Learned. Repeat it a few times and ARIA will grow confident.");
    await refresh();
  }

  const statistical = profile?.patterns.filter(
    (p) => !p.dimension.startsWith("rule:") && !p.dimension.startsWith("edit:"),
  );
  const edits = profile?.patterns.filter((p) => p.dimension.startsWith("edit:"));
  const rules = profile?.patterns.filter((p) => p.dimension.startsWith("rule:"));

  return (
    <div className="mx-auto max-w-3xl">
      <h2 className="mb-1 text-2xl font-semibold">Communication profile</h2>
      <p className="mb-6 text-sm text-zinc-400">
        How ARIA thinks you write, measured from your real messages. Every
        pattern shows its evidence — and you can delete anything that&apos;s wrong.
      </p>

      {error && <p role="alert" className="mb-4 text-sm text-red-400">{error}</p>}
      {note && <p className="mb-4 text-sm text-cyan-300">{note}</p>}

      {/* Voice readiness. Shown first because it is the single gate between
          drafting and autonomous replying, and until now the only way to see
          it was to ask the autonomy engine about a specific contact. */}
      {readiness && (
        <section className="glass mb-6 rounded-xl p-5">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="text-sm font-medium">Can ARIA write as you?</h3>
            <span
              className={`text-sm font-semibold ${
                readiness.ready_for_autonomy ? "text-emerald-300" : "text-amber-300"
              }`}
            >
              {(readiness.confidence * 100).toFixed(0)}% / need{" "}
              {(readiness.required_confidence * 100).toFixed(0)}%
            </span>
          </div>

          <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-white/10">
            <div
              className={`h-full rounded-full ${
                readiness.ready_for_autonomy ? "bg-emerald-400/80" : "bg-amber-400/80"
              }`}
              style={{
                width: `${Math.min(
                  100,
                  Math.round(
                    (readiness.confidence / readiness.required_confidence) * 100,
                  ),
                )}%`,
              }}
            />
          </div>

          <p className="mt-3 text-xs text-zinc-400">
            {readiness.ready_for_autonomy ? (
              <>
                Learned from <strong>{readiness.samples}</strong> of your messages.
                ARIA can reply on her own to contacts you have enabled.
              </>
            ) : (
              <>
                Learned from <strong>{readiness.samples}</strong> of your messages.
                About <strong>{readiness.samples_needed}</strong> more would let
                her reply on her own. Until then she drafts and you send.
              </>
            )}
          </p>

          <div className="mt-4">
            <label
              htmlFor="samples"
              className="block text-xs font-medium text-zinc-300"
            >
              Paste messages you have actually sent — one per line
            </label>
            <p className="mb-2 mt-1 text-[11px] text-zinc-500">
              Copy a few real replies from WhatsApp. They must be your own
              words: ARIA will not invent samples of how you write, because
              she would then send that invented voice to real people in your
              name.
            </p>
            <textarea
              id="samples"
              value={samples}
              onChange={(e) => setSamples(e.target.value)}
              rows={6}
              placeholder={"hey bro, sawa see you at 5\njust checking if you got the file\nasante, appreciate it"}
              className="w-full rounded-lg bg-black/30 p-3 font-mono text-xs text-zinc-200 outline-none ring-1 ring-white/10 focus:ring-cyan-500/40"
            />

            <div className="mt-3">
              <label
                htmlFor="audience"
                className="block text-xs font-medium text-zinc-300"
              >
                Who was this writing for?
              </label>
              <p className="mb-2 mt-1 text-[11px] text-zinc-500">
                If these messages all went to one kind of person, say so. Their
                phrases then stay with that audience — words meant for your
                partner will never turn up in a reply to a recruiter. Leave it
                blank only for a mixed set that represents how you write in
                general.
              </p>
              <select
                id="audience"
                value={sampleAudience}
                onChange={(e) => setSampleAudience(e.target.value)}
                className="rounded-lg bg-black/30 px-3 py-2 text-xs text-zinc-200 outline-none ring-1 ring-white/10 focus:ring-cyan-500/40"
              >
                <option value="">how I write in general</option>
                {RELATIONSHIPS.map((r) => (
                  <option key={r} value={r}>
                    to {r} contacts
                  </option>
                ))}
              </select>
            </div>

            <button
              onClick={addSamples}
              disabled={busy || !samples.trim()}
              className="mt-2 rounded-lg bg-cyan-500/20 px-4 py-2 text-sm text-cyan-200 hover:bg-cyan-500/30 disabled:opacity-40"
            >
              Teach ARIA my voice
            </button>
          </div>
        </section>
      )}

      <button
        onClick={relearn}
        disabled={busy}
        className="mb-6 flex items-center gap-2 rounded-md bg-cyan-600 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-500 disabled:opacity-40"
      >
        <RefreshCw size={14} aria-hidden />
        {busy ? "Measuring…" : "Re-measure every layer"}
      </button>

      {/* The layers themselves. ARIA does not have one voice — she has a
          general one and a more specific one per audience, and which patterns
          reach a given reply depends on who it is going to. */}
      {profile && profile.scopes.length > 1 && (
        <section className="glass mb-6 rounded-xl p-4">
          <h3 className="mb-1 text-sm font-medium">Your voices</h3>
          <p className="mb-3 text-xs text-zinc-500">
            A reply is built from the general layer, then the layer for that
            relationship, then the layer for that person — each overriding the
            one before. Click a layer to see only what it holds.
          </p>
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => setViewScope("")}
              className={`rounded-full px-3 py-1 text-xs ring-1 ${
                viewScope === ""
                  ? "bg-cyan-500/20 text-cyan-200 ring-cyan-500/40"
                  : "text-zinc-400 ring-white/10 hover:text-zinc-200"
              }`}
            >
              everything
            </button>
            {profile.scopes.map((s) => (
              <button
                key={s.scope}
                onClick={() => setViewScope(s.scope)}
                title={`${s.pattern_count} patterns · ${s.evidence} samples · confidence ${s.confidence.toFixed(2)}`}
                className={`rounded-full px-3 py-1 text-xs ring-1 ${
                  viewScope === s.scope
                    ? "bg-cyan-500/20 text-cyan-200 ring-cyan-500/40"
                    : "text-zinc-400 ring-white/10 hover:text-zinc-200"
                }`}
              >
                {s.description}
                <span className="ml-1.5 text-zinc-500">{s.evidence}</span>
              </button>
            ))}
          </div>
        </section>
      )}

      {/* Teach a rule directly */}
      <section className="glass mb-6 rounded-xl p-4">
        <h3 className="mb-1 text-sm font-medium">Teach ARIA directly</h3>
        <p className="mb-3 text-xs text-zinc-500">
          State a preference in your own words. Stored at high confidence —
          you said it, ARIA didn&apos;t guess it.
        </p>
        <form onSubmit={teach} className="flex gap-2">
          <input
            value={rule}
            onChange={(e) => setRule(e.target.value)}
            placeholder="e.g. Never use 'Dear Sir/Madam'"
            aria-label="Style rule"
            className="flex-1 rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm outline-none focus:border-zinc-500"
          />
          <button className="rounded-md bg-zinc-100 px-3 py-2 text-sm font-medium text-zinc-900 hover:bg-white">
            Add rule
          </button>
        </form>
      </section>

      {/* Show ARIA an edit */}
      <section className="glass mb-6 rounded-xl p-4">
        <h3 className="mb-1 text-sm font-medium">Correct a draft</h3>
        <p className="mb-3 text-xs text-zinc-500">
          Paste something ARIA wrote and how you&apos;d actually say it.
          Preview first — nothing is learned until you choose.
        </p>
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          rows={2}
          placeholder="ARIA's version…"
          aria-label="ARIA draft"
          className="mb-2 w-full rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm outline-none focus:border-zinc-500"
        />
        <textarea
          value={final}
          onChange={(e) => setFinal(e.target.value)}
          rows={2}
          placeholder="How you'd actually write it…"
          aria-label="Your version"
          className="mb-2 w-full rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm outline-none focus:border-zinc-500"
        />
        <div className="flex gap-2">
          <button
            onClick={preview}
            disabled={!draft.trim() || !final.trim()}
            className="rounded-md border border-zinc-700 px-3 py-1.5 text-xs text-zinc-300 hover:text-white disabled:opacity-40"
          >
            Preview what ARIA would learn
          </button>
          <button
            onClick={commitLesson}
            disabled={!draft.trim() || !final.trim()}
            className="rounded-md bg-cyan-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-cyan-500 disabled:opacity-40"
          >
            Teach this
          </button>
        </div>
        {lessons !== null && (
          <ul className="mt-3 space-y-1 border-t border-white/10 pt-3">
            {lessons.length ? (
              lessons.map((l, i) => (
                <li key={i} className="text-sm text-cyan-300">• {l}</li>
              ))
            ) : (
              <li className="text-sm text-zinc-500">
                No clear lesson — the two versions are too similar.
              </li>
            )}
          </ul>
        )}
      </section>

      {/* Learned patterns */}
      {[
        { title: "Explicit rules you gave", items: rules },
        { title: "Measured from your writing", items: statistical },
        { title: "Learned from your edits", items: edits },
      ].map(({ title, items }) =>
        items && items.length > 0 ? (
          <section key={title} className="mb-6">
            <h3 className="mb-2 text-sm font-medium text-zinc-300">{title}</h3>
            <ul className="space-y-2">
              {items.map((p) => (
                <li key={p.id} className="glass rounded-xl p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="text-sm">{p.value}</p>
                      <p className="mt-1 text-xs text-zinc-500">
                        <span className={confidenceColor(p.confidence)}>
                          {confidenceLabel(p.confidence)} ({p.confidence.toFixed(2)})
                        </span>
                        {" · "}
                        {p.evidence_count} sample{p.evidence_count === 1 ? "" : "s"}
                        {" · "}
                        {p.source}
                        {p.scope !== "global" && (
                          <>
                            {" · "}
                            <span className="text-cyan-400/80">
                              {profile?.scopes.find((s) => s.scope === p.scope)
                                ?.description ?? p.scope}
                            </span>
                          </>
                        )}
                      </p>
                    </div>
                    <button
                      onClick={() => api.forgetStylePattern(p.id).then(refresh)}
                      className="shrink-0 text-xs text-zinc-600 hover:text-red-400"
                    >
                      Forget
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        ) : null,
      )}

      {profile && profile.patterns.length === 0 && (
        <p className="text-sm text-zinc-500">
          Nothing learned yet. ARIA learns from messages you send — connect
          WhatsApp, or teach her a rule above.
        </p>
      )}

      {/* Full transparency: exactly what goes into the prompt */}
      {profile && (
        <details className="mt-8">
          <summary className="cursor-pointer text-xs text-zinc-500 hover:text-zinc-300">
            Show exactly what ARIA reads before drafting
          </summary>
          <pre className="glass mt-2 overflow-x-auto rounded-xl p-4 text-xs text-zinc-400">
            {profile.prompt_block}
          </pre>
        </details>
      )}
    </div>
  );
}
