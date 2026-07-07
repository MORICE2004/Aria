/**
 * Approvals — the human side of the Action Gateway.
 *
 * Every sensitive action any agent wants to take appears here as a card:
 * what, why, and the EXACT payload it will act on. Nothing runs until you
 * press Approve; Reject buries it permanently. The audit trail under each
 * card shows the full history of the request.
 */
"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type ActionRequest, type AuditEvent } from "@/lib/api";

const STATUS_COLORS: Record<ActionRequest["status"], string> = {
  pending: "text-amber-400",
  approved: "text-sky-400",
  executed: "text-emerald-400",
  rejected: "text-zinc-500",
  failed: "text-red-400",
};

export default function ApprovalsPage() {
  const [actions, setActions] = useState<ActionRequest[]>([]);
  const [audits, setAudits] = useState<Record<string, AuditEvent[]>>({});
  const [demoMessage, setDemoMessage] = useState("");
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(
    () => api.listActions().then(setActions).catch((e: Error) => setError(e.message)),
    [],
  );

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function decide(id: string, approve: boolean) {
    setError(null);
    try {
      if (approve) await api.approveAction(id);
      else await api.rejectAction(id, "Rejected from dashboard");
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function toggleAudit(id: string) {
    if (audits[id]) {
      setAudits((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
    } else {
      const trail = await api.getAudit(id);
      setAudits((prev) => ({ ...prev, [id]: trail }));
    }
  }

  async function createDemo(e: React.FormEvent) {
    e.preventDefault();
    if (!demoMessage.trim()) return;
    await api.createDemoAction(demoMessage.trim());
    setDemoMessage("");
    await refresh();
  }

  const pending = actions.filter((a) => a.status === "pending");
  const decided = actions.filter((a) => a.status !== "pending");

  return (
    <div className="mx-auto max-w-3xl">
      <h2 className="mb-1 text-2xl font-semibold">Approvals</h2>
      <p className="mb-6 text-sm text-zinc-400">
        Nothing leaves this machine as “you” without passing through this
        queue. Agents draft; you decide.
      </p>

      {error && (
        <p role="alert" className="mb-4 text-xs text-red-400">
          {error}
        </p>
      )}

      {/* Demo generator — lets you exercise the flow before real agents exist */}
      <form
        onSubmit={createDemo}
        className="mb-8 flex gap-2 rounded-lg border border-dashed border-zinc-700 bg-zinc-900/50 p-3"
      >
        <input
          value={demoMessage}
          onChange={(e) => setDemoMessage(e.target.value)}
          placeholder="Try it: type a message for the demo agent to 'send'…"
          aria-label="Demo action message"
          className="flex-1 rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm outline-none focus:border-zinc-500"
        />
        <button className="rounded-md bg-zinc-100 px-3 py-2 text-sm font-medium text-zinc-900 hover:bg-white">
          Create demo request
        </button>
      </form>

      <h3 className="mb-2 text-sm font-medium text-zinc-300">
        Awaiting your decision ({pending.length})
      </h3>
      <ul className="mb-8 space-y-3">
        {pending.map((a) => (
          <li key={a.id} className="rounded-lg border border-amber-500/30 bg-zinc-900 p-4">
            <p className="mb-1 text-sm font-medium">{a.summary}</p>
            <p className="mb-3 text-xs text-zinc-500">
              agent: {a.agent} · action: {a.action_type}
            </p>
            <pre className="mb-3 overflow-x-auto rounded bg-zinc-950 p-2 text-xs text-zinc-400">
              {JSON.stringify(a.payload, null, 2)}
            </pre>
            <div className="flex gap-2">
              <button
                onClick={() => decide(a.id, true)}
                className="rounded-md bg-emerald-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-emerald-500"
              >
                Approve
              </button>
              <button
                onClick={() => decide(a.id, false)}
                className="rounded-md border border-zinc-700 px-4 py-1.5 text-sm text-zinc-300 hover:border-red-500 hover:text-red-400"
              >
                Reject
              </button>
            </div>
          </li>
        ))}
        {pending.length === 0 && (
          <p className="text-sm text-zinc-500">Queue is empty — nothing needs you.</p>
        )}
      </ul>

      <h3 className="mb-2 text-sm font-medium text-zinc-300">History</h3>
      <ul className="space-y-2">
        {decided.map((a) => (
          <li key={a.id} className="rounded-lg border border-zinc-800 bg-zinc-900 p-3">
            <div className="flex items-center justify-between">
              <span className="text-sm">{a.summary}</span>
              <span className={`text-xs font-medium uppercase ${STATUS_COLORS[a.status]}`}>
                {a.status}
              </span>
            </div>
            {a.result && <p className="mt-1 text-xs text-zinc-500">{a.result}</p>}
            <button
              onClick={() => toggleAudit(a.id)}
              className="mt-2 text-xs text-zinc-500 underline-offset-2 hover:text-zinc-300 hover:underline"
            >
              {audits[a.id] ? "Hide audit trail" : "Show audit trail"}
            </button>
            {audits[a.id] && (
              <ol className="mt-2 space-y-1 border-l border-zinc-700 pl-3">
                {audits[a.id].map((e, i) => (
                  <li key={i} className="text-xs text-zinc-400">
                    <span className="font-medium">{e.event}</span>
                    {e.detail && ` — ${e.detail}`}
                    <span className="ml-1 text-zinc-600">
                      {new Date(e.created_at).toLocaleString()}
                    </span>
                  </li>
                ))}
              </ol>
            )}
          </li>
        ))}
        {decided.length === 0 && <p className="text-sm text-zinc-500">No history yet.</p>}
      </ul>
    </div>
  );
}
