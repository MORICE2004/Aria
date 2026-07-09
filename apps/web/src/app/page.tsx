/**
 * Home — ARIA's command center.
 *
 * Greeting, system status (live /health check), and stat tiles pulled from
 * the real APIs: pending approvals, open tasks, tracked jobs, memories.
 * Everything links into its section.
 */
"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, API_URL } from "../lib/api";

type ApiStatus =
  | { state: "loading" }
  | { state: "ok"; env: string; version: string }
  | { state: "down"; error: string };

type Stats = {
  pendingApprovals: number;
  openTasks: number;
  jobs: number;
  memories: number;
};

function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 5) return "Working late";
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

export default function HomePage() {
  const [status, setStatus] = useState<ApiStatus>({ state: "loading" });
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => {
    fetch(`${API_URL}/health`)
      .then((res) => {
        if (!res.ok) throw new Error(`API responded with ${res.status}`);
        return res.json();
      })
      .then((body: { env: string; version: string }) =>
        setStatus({ state: "ok", env: body.env, version: body.version }),
      )
      .catch((err: Error) => setStatus({ state: "down", error: err.message }));

    Promise.all([
      api.listActions("pending"),
      api.listTasks("open"),
      api.listJobs(),
      api.listMemories(),
    ])
      .then(([actions, tasks, jobs, memories]) =>
        setStats({
          pendingApprovals: actions.length,
          openTasks: tasks.length,
          jobs: jobs.length,
          memories: memories.length,
        }),
      )
      .catch(() => setStats(null));
  }, []);

  const tiles = stats
    ? ([
        { label: "Awaiting your approval", value: stats.pendingApprovals, href: "/approvals", hot: stats.pendingApprovals > 0 },
        { label: "Open tasks", value: stats.openTasks, href: "/tasks", hot: false },
        { label: "Jobs tracked", value: stats.jobs, href: "/jobs", hot: false },
        { label: "Memories", value: stats.memories, href: "/memory", hot: false },
      ] as const)
    : null;

  return (
    <div className="mx-auto max-w-4xl">
      {/* Hero */}
      <section className="mb-8 mt-4 md:mt-10">
        <p className="mb-1 text-xs uppercase tracking-[0.3em] text-cyan-400/80">
          {greeting()}, MORICE
        </p>
        <h1 className="text-3xl font-semibold tracking-tight md:text-4xl">
          At your service.
        </h1>
        <p className="mt-2 max-w-lg text-sm text-zinc-400">
          I draft, score, remember, and prepare — and nothing leaves this
          machine as you without your explicit approval.
        </p>
      </section>

      {/* System status */}
      <section className="glass mb-6 flex items-center gap-3 rounded-xl px-5 py-4">
        {status.state === "ok" ? (
          <>
            <span aria-hidden className="reactor h-2.5 w-2.5 rounded-full bg-cyan-400" />
            <span className="text-sm">
              All systems online
              <span className="ml-2 text-xs text-zinc-500">
                v{status.version} · {status.env}
              </span>
            </span>
            <Link
              href="/chat"
              className="ml-auto rounded-lg bg-cyan-500/90 px-4 py-2 text-sm font-medium text-cyan-950 transition-colors hover:bg-cyan-400"
            >
              Talk to ARIA
            </Link>
          </>
        ) : status.state === "loading" ? (
          <span className="text-sm text-zinc-500">Contacting core…</span>
        ) : (
          <>
            <span aria-hidden className="h-2.5 w-2.5 rounded-full bg-red-500" />
            <span className="text-sm">
              Core offline — start the API:{" "}
              <code className="rounded bg-white/5 px-1.5 py-0.5 text-xs">
                uvicorn src.main:app --reload --port 8000
              </code>
            </span>
          </>
        )}
      </section>

      {/* Stat tiles */}
      {tiles && (
        <section className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {tiles.map((tile) => (
            <Link
              key={tile.href}
              href={tile.href}
              className={`glass group rounded-xl p-4 transition-colors hover:border-cyan-400/30 ${
                tile.hot ? "border-amber-400/40" : ""
              }`}
            >
              <p
                className={`text-3xl font-semibold tabular-nums ${
                  tile.hot ? "text-amber-300" : "text-zinc-100"
                }`}
              >
                {tile.value}
              </p>
              <p className="mt-1 text-xs text-zinc-500 group-hover:text-zinc-400">
                {tile.label}
              </p>
            </Link>
          ))}
        </section>
      )}
    </div>
  );
}
