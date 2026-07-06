/**
 * Home page — system status.
 *
 * Phase 0's job is proving the full pipeline works: this page calls the
 * FastAPI backend's /health endpoint from the browser and shows the result.
 * If the API is down (or not started), it says so honestly instead of erroring.
 */
"use client";

import { useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type ApiStatus =
  | { state: "loading" }
  | { state: "ok"; env: string; version: string }
  | { state: "down"; error: string };

export default function HomePage() {
  const [status, setStatus] = useState<ApiStatus>({ state: "loading" });

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
  }, []);

  return (
    <div className="mx-auto max-w-2xl">
      <h2 className="mb-2 text-2xl font-semibold">Welcome to ARIA</h2>
      <p className="mb-8 text-sm text-zinc-400">
        Your personal AI operating system. Phase 0 verifies the foundation:
        dashboard, API, and databases all talking to each other.
      </p>

      <section className="rounded-lg border border-zinc-800 bg-zinc-900 p-5">
        <h3 className="mb-3 text-sm font-medium text-zinc-300">
          System status
        </h3>

        {status.state === "loading" && (
          <p className="text-sm text-zinc-500">Checking API…</p>
        )}

        {status.state === "ok" && (
          <div className="flex items-center gap-2 text-sm">
            <span aria-hidden className="h-2 w-2 rounded-full bg-emerald-500" />
            <span>
              API online — version {status.version} ({status.env})
            </span>
          </div>
        )}

        {status.state === "down" && (
          <div className="text-sm">
            <div className="flex items-center gap-2">
              <span aria-hidden className="h-2 w-2 rounded-full bg-red-500" />
              <span>API unreachable: {status.error}</span>
            </div>
            <p className="mt-2 text-zinc-500">
              Start it with:{" "}
              <code className="rounded bg-zinc-800 px-1.5 py-0.5">
                uvicorn src.main:app --reload --port 8000
              </code>{" "}
              in <code className="rounded bg-zinc-800 px-1.5 py-0.5">apps/api</code>
            </p>
          </div>
        )}
      </section>
    </div>
  );
}
