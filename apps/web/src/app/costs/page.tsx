/**
 * Costs — what ARIA has spent, and how much work stayed local.
 *
 * The second number is the point: the model router exists to keep routine
 * work on free local models, and this page shows whether it is working.
 */
"use client";

import { useEffect, useState } from "react";
import { API_URL } from "@/lib/api";

type Totals = {
  calls: number;
  input_tokens: number;
  output_tokens: number;
  estimated_cost_usd: number;
};
type Summary = {
  totals: Record<string, Totals>;
  by_model: {
    model: string;
    tier: string;
    calls: number;
    estimated_cost_usd: number;
    local: boolean;
  }[];
  local_share_pct: number;
  note: string;
};

const PERIODS: [string, string][] = [
  ["today", "Last 24 hours"],
  ["week", "Last 7 days"],
  ["month", "Last 30 days"],
  ["all_time", "All time"],
];

export default function CostsPage() {
  const [data, setData] = useState<Summary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API_URL}/costs`)
      .then((r) => r.json())
      .then(setData)
      .catch((e: Error) => setError(e.message));
  }, []);

  return (
    <div className="mx-auto max-w-3xl">
      <h2 className="mb-1 text-2xl font-semibold">Costs</h2>
      <p className="mb-6 text-sm text-zinc-400">
        Every model call ARIA makes, and what it plausibly cost.
      </p>

      {error && <p role="alert" className="mb-4 text-sm text-red-400">{error}</p>}

      {data && (
        <>
          {/* The headline number: how much stayed free and private */}
          <section className="glass mb-6 rounded-xl p-5">
            <p className="text-3xl font-semibold text-emerald-400">
              {data.local_share_pct}%
            </p>
            <p className="mt-1 text-sm text-zinc-400">
              of calls ran on a local model — free, and the content never left
              this machine.
            </p>
          </section>

          <section className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4">
            {PERIODS.map(([key, label]) => {
              const t = data.totals[key];
              if (!t) return null;
              return (
                <div key={key} className="glass rounded-xl p-4">
                  <p className="text-2xl font-semibold tabular-nums">
                    ${t.estimated_cost_usd.toFixed(4)}
                  </p>
                  <p className="mt-1 text-xs text-zinc-500">{label}</p>
                  <p className="mt-2 text-[11px] text-zinc-600">
                    {t.calls} call{t.calls === 1 ? "" : "s"} ·{" "}
                    {(t.input_tokens + t.output_tokens).toLocaleString()} tokens
                  </p>
                </div>
              );
            })}
          </section>

          <h3 className="mb-2 text-sm font-medium text-zinc-300">By model</h3>
          {data.by_model.length === 0 ? (
            <p className="text-sm text-zinc-500">
              No calls recorded yet. Use chat or the job analyser and come back.
            </p>
          ) : (
            <ul className="space-y-2">
              {data.by_model.map((m) => (
                <li
                  key={`${m.model}-${m.tier}`}
                  className="glass flex items-center gap-3 rounded-xl px-4 py-3"
                >
                  <span
                    aria-hidden
                    className={`h-2 w-2 shrink-0 rounded-full ${
                      m.local ? "bg-emerald-500" : "bg-cyan-400"
                    }`}
                  />
                  <span className="flex-1 truncate text-sm">{m.model}</span>
                  <span className="text-xs text-zinc-500">
                    {m.local ? "local" : "cloud"}
                  </span>
                  <span className="text-xs text-zinc-500">{m.calls} calls</span>
                  <span className="w-20 text-right text-sm tabular-nums">
                    ${m.estimated_cost_usd.toFixed(4)}
                  </span>
                </li>
              ))}
            </ul>
          )}

          <p className="mt-6 text-xs text-zinc-600">{data.note}</p>
        </>
      )}
    </div>
  );
}
