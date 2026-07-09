/**
 * Learning — your programming coach.
 *
 * Left: the topic tracker (what you're learning, with progress status). The
 * coach reads this list on every request, so keeping it honest makes every
 * explanation better-pitched. Right: three tools — Explain, Review my code,
 * and Learning path.
 */
"use client";

import { useEffect, useState } from "react";
import { api, type LearningTopic } from "@/lib/api";

const STATUSES = ["learning", "comfortable", "mastered"] as const;
const STATUS_COLOR: Record<(typeof STATUSES)[number], string> = {
  learning: "text-amber-400",
  comfortable: "text-sky-400",
  mastered: "text-emerald-400",
};

type Tool = "explain" | "review" | "path";

export default function LearningPage() {
  const [topics, setTopics] = useState<LearningTopic[]>([]);
  const [newTopic, setNewTopic] = useState("");
  const [tool, setTool] = useState<Tool>("explain");
  const [inputA, setInputA] = useState(""); // concept | code | goal
  const [inputB, setInputB] = useState(""); // context | question | (unused)
  const [output, setOutput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = () =>
    api.listTopics().then(setTopics).catch((e: Error) => setError(e.message));

  useEffect(() => {
    refresh();
  }, []);

  async function addTopic(e: React.FormEvent) {
    e.preventDefault();
    if (!newTopic.trim()) return;
    await api.addTopic(newTopic.trim());
    setNewTopic("");
    await refresh();
  }

  async function run() {
    if (!inputA.trim() || busy) return;
    setBusy(true);
    setError(null);
    setOutput("");
    try {
      const result =
        tool === "explain"
          ? await api.explain(inputA, inputB)
          : tool === "review"
            ? await api.reviewCode(inputA, inputB)
            : await api.learningPath(inputA);
      setOutput(result.text);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const LABELS: Record<Tool, { a: string; b: string | null; button: string; rows: number }> = {
    explain: { a: "What concept should I explain? (e.g. 'async/await')", b: "Where did you run into it? (optional)", button: "Explain it", rows: 2 },
    review: { a: "Paste your code here…", b: "What do you want to know about it? (optional)", button: "Review my code", rows: 10 },
    path: { a: "What's your goal? (e.g. 'become a backend developer')", b: null, button: "Build my path", rows: 2 },
  };
  const labels = LABELS[tool];

  return (
    <div className="mx-auto flex max-w-5xl gap-6">
      {/* Topic tracker */}
      <aside className="w-72 shrink-0">
        <h2 className="mb-1 text-xl font-semibold">Learning</h2>
        <p className="mb-4 text-xs text-zinc-500">
          Track what you&apos;re learning — the coach reads this list and
          pitches every answer at your level.
        </p>
        <form onSubmit={addTopic} className="mb-3 flex gap-2">
          <input
            value={newTopic}
            onChange={(e) => setNewTopic(e.target.value)}
            placeholder="Add a topic…"
            aria-label="New topic"
            className="min-w-0 flex-1 rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm outline-none focus:border-zinc-500"
          />
          <button className="rounded-md bg-zinc-100 px-3 py-2 text-sm font-medium text-zinc-900 hover:bg-white">
            +
          </button>
        </form>
        <ul className="space-y-2">
          {topics.map((t) => (
            <li key={t.id} className="rounded-lg border border-zinc-800 bg-zinc-900 p-3">
              <div className="flex items-center justify-between">
                <span className="text-sm">{t.name}</span>
                <button
                  onClick={() => api.deleteTopic(t.id).then(refresh)}
                  aria-label={`Delete ${t.name}`}
                  className="text-xs text-zinc-600 hover:text-red-400"
                >
                  ✕
                </button>
              </div>
              <div className="mt-2 flex gap-1">
                {STATUSES.map((s) => (
                  <button
                    key={s}
                    onClick={() => api.updateTopic(t.id, s).then(refresh)}
                    className={`rounded px-1.5 py-0.5 text-[10px] capitalize ${
                      t.status === s
                        ? `bg-zinc-800 font-semibold ${STATUS_COLOR[s]}`
                        : "text-zinc-600 hover:text-zinc-300"
                    }`}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </li>
          ))}
          {topics.length === 0 && (
            <p className="text-xs text-zinc-600">
              Nothing yet — add “Python basics” to get started.
            </p>
          )}
        </ul>
      </aside>

      {/* Coach tools */}
      <section className="flex-1">
        <div className="mb-4 flex gap-2">
          {(["explain", "review", "path"] as Tool[]).map((t) => (
            <button
              key={t}
              onClick={() => {
                setTool(t);
                setInputA("");
                setInputB("");
                setOutput("");
              }}
              className={`rounded-md px-3 py-1.5 text-sm capitalize ${
                tool === t
                  ? "bg-indigo-600 text-white"
                  : "border border-zinc-700 text-zinc-400 hover:text-white"
              }`}
            >
              {t === "review" ? "Review code" : t === "path" ? "Learning path" : "Explain"}
            </button>
          ))}
        </div>

        <textarea
          value={inputA}
          onChange={(e) => setInputA(e.target.value)}
          placeholder={labels.a}
          aria-label={labels.a}
          rows={labels.rows}
          className="mb-2 w-full rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 font-mono text-sm outline-none focus:border-zinc-500"
        />
        {labels.b && (
          <input
            value={inputB}
            onChange={(e) => setInputB(e.target.value)}
            placeholder={labels.b}
            aria-label={labels.b}
            className="mb-2 w-full rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm outline-none focus:border-zinc-500"
          />
        )}
        <button
          onClick={run}
          disabled={busy || !inputA.trim()}
          className="mb-4 rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-40"
        >
          {busy ? "Thinking…" : labels.button}
        </button>

        {error && (
          <p role="alert" className="mb-4 text-sm text-red-400">{error}</p>
        )}
        {output && (
          <div className="whitespace-pre-wrap rounded-lg border border-zinc-800 bg-zinc-900 p-4 text-sm text-zinc-200">
            {output}
          </div>
        )}
      </section>
    </div>
  );
}
