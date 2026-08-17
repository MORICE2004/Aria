/**
 * Home — ARIA's command center.
 *
 * The briefing comes first, because the question this page exists to answer is
 * "what happened while I was away?" — and it is the same question whether the
 * page is open on a phone or a desktop. Status and tiles follow it.
 *
 * Everything shown is real: the briefing is assembled from records by the API,
 * the status is a live /health check, the tiles are counts from real endpoints.
 */
"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, API_URL, type Briefing } from "../lib/api";

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
  const [briefing, setBriefing] = useState<Briefing | null>(null);
  const [hours, setHours] = useState(24);

  useEffect(() => {
    api.getBriefing(hours).then(setBriefing).catch(() => setBriefing(null));
  }, [hours]);

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

      {/* Briefing. First, and always shown — including when there is nothing
          to report, because "nothing happened" is the answer he came for. */}
      {briefing && (
        <section className="glass mb-6 rounded-xl p-5">
          <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-sm font-medium">
              While you were away
              <span className="ml-2 text-xs text-zinc-500">
                last {briefing.hours === 24 ? "24 hours" : `${briefing.hours}h`}
              </span>
            </h2>
            <div className="flex gap-1">
              {[6, 24, 72].map((h) => (
                <button
                  key={h}
                  onClick={() => setHours(h)}
                  className={`rounded-full px-2.5 py-0.5 text-[11px] ring-1 ${
                    hours === h
                      ? "bg-cyan-500/20 text-cyan-200 ring-cyan-500/40"
                      : "text-zinc-500 ring-white/10 hover:text-zinc-300"
                  }`}
                >
                  {h}h
                </button>
              ))}
            </div>
          </div>

          <p className="text-sm text-zinc-200">{briefing.headline}</p>

          {briefing.quiet ? (
            <p className="mt-2 text-xs text-zinc-500">
              Nothing is being hidden here — there are no records in this
              period.
            </p>
          ) : (
            <ul className="mt-4 space-y-3">
              {briefing.sections.map((section) => (
                <li key={section.key}>
                  <p className="flex items-baseline gap-2 text-xs">
                    <span
                      aria-hidden
                      className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                        section.needs_attention ? "bg-amber-400" : "bg-zinc-600"
                      }`}
                    />
                    <span className="font-medium text-zinc-300">
                      {section.heading}
                    </span>
                    <span className="text-zinc-500">{section.summary}</span>
                  </p>
                  {section.items.length > 0 && (
                    <ul className="ml-3.5 mt-1 space-y-1 border-l border-white/10 pl-3">
                      {section.items.map((item, i) => (
                        <li key={`${section.key}-${i}`} className="text-xs">
                          <Link
                            href={item.link || "/"}
                            className="text-zinc-400 hover:text-cyan-300"
                          >
                            {item.title}
                          </Link>
                          {item.detail && (
                            <span className="ml-1 text-zinc-600">
                              — {item.detail}
                            </span>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

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
