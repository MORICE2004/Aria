/**
 * ARIA Autonomous Activity — what she is doing, and how to stop her.
 *
 * The page exists so autonomy is never something MORICE has to take on trust.
 * Three design decisions follow from that:
 *
 *   1. The stop controls are at the TOP, always visible, never behind a menu.
 *      If he wants to stop ARIA he is probably already unhappy; making him
 *      hunt for the button is the wrong moment to be clever about layout.
 *
 *   2. Every autonomous message shows the reasons it was allowed. A list of
 *      things ARIA sent is a log; a list with justifications is supervision.
 *
 *   3. Unreviewed responses are counted and labelled as unreviewed, never
 *      folded into a "success" figure. Silence is not approval, and the
 *      dashboard must not quietly imply that it is.
 */
"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  Ban,
  Bot,
  CheckCircle2,
  CircleSlash,
  Coins,
  Hand,
  Inbox,
  OctagonX,
  Pause,
  Pencil,
  Play,
  RefreshCw,
  ShieldAlert,
} from "lucide-react";

import {
  api,
  type WaActivity,
  type WaAutonomousResponse,
  type WaReadiness,
} from "@/lib/api";

const RISK_STYLES: Record<string, string> = {
  low: "bg-emerald-500/10 text-emerald-300 ring-emerald-500/30",
  medium: "bg-amber-500/10 text-amber-300 ring-amber-500/30",
  high: "bg-orange-500/10 text-orange-300 ring-orange-500/30",
  critical: "bg-red-500/10 text-red-300 ring-red-500/30",
};

function Stat({
  label,
  value,
  hint,
  icon: Icon,
  tone = "default",
}: {
  label: string;
  value: string | number;
  hint?: string;
  icon: typeof Inbox;
  tone?: "default" | "warn" | "danger" | "good";
}) {
  const tones = {
    default: "text-zinc-100",
    good: "text-emerald-300",
    warn: "text-amber-300",
    danger: "text-red-300",
  };
  return (
    <div className="glass rounded-xl p-4">
      <div className="flex items-center gap-2 text-[11px] uppercase tracking-widest text-zinc-500">
        <Icon className="h-3.5 w-3.5" aria-hidden />
        {label}
      </div>
      <div className={`mt-2 text-2xl font-semibold ${tones[tone]}`}>{value}</div>
      {hint && <p className="mt-1 text-xs text-zinc-500">{hint}</p>}
    </div>
  );
}

function RiskBadge({ level }: { level: string }) {
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider ring-1 ${
        RISK_STYLES[level] ?? "bg-zinc-500/10 text-zinc-300 ring-zinc-500/30"
      }`}
    >
      {level || "unknown"}
    </span>
  );
}

export default function ActivityPage() {
  const [activity, setActivity] = useState<WaActivity | null>(null);
  const [responses, setResponses] = useState<WaAutonomousResponse[]>([]);
  const [readiness, setReadiness] = useState<WaReadiness | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [correction, setCorrection] = useState("");

  const load = useCallback(async () => {
    try {
      const [a, r, k] = await Promise.all([
        api.waActivity(),
        api.waAutonomousResponses(),
        api.waReadiness(),
      ]);
      setActivity(a);
      setResponses(r);
      setReadiness(k);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load activity");
    }
  }, []);

  useEffect(() => {
    // Autonomy is live behaviour, so the page refreshes itself. Ten seconds
    // is frequent enough to notice something going wrong while it is still
    // worth stopping. The first load is deferred to a timeout rather than run
    // in the effect body, so the effect only ever schedules work.
    const first = setTimeout(load, 0);
    const timer = setInterval(load, 10_000);
    return () => {
      clearTimeout(first);
      clearInterval(timer);
    };
  }, [load]);

  async function control(action: () => Promise<unknown>) {
    setBusy(true);
    try {
      await action();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusy(false);
    }
  }

  async function react(id: string, reaction: string, text = "") {
    await control(async () => {
      await api.waReactToResponse(id, reaction, text);
      setEditing(null);
      setCorrection("");
    });
  }

  if (!activity) {
    return (
      <main className="p-6">
        <h1 className="text-2xl font-semibold">Autonomous Activity</h1>
        <p className="mt-4 text-sm text-zinc-500">
          {error || "Loading what ARIA has been doing…"}
        </p>
      </main>
    );
  }

  const stopped = activity.emergency_stop || activity.paused;

  return (
    <main className="space-y-6 p-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Autonomous Activity</h1>
          <p className="mt-1 max-w-2xl text-sm text-zinc-400">
            {activity.mode_description}
          </p>
        </div>
        <button
          onClick={load}
          className="glass flex items-center gap-2 rounded-lg px-3 py-2 text-xs text-zinc-300 hover:text-white"
        >
          <RefreshCw className="h-3.5 w-3.5" aria-hidden /> Refresh
        </button>
      </header>

      {error && (
        <div className="rounded-lg bg-red-500/10 px-4 py-3 text-sm text-red-300 ring-1 ring-red-500/30">
          {error}
        </div>
      )}

      {/* --- Stop controls. Deliberately first on the page. --- */}
      <section
        className={`glass rounded-xl p-4 ring-1 ${
          stopped ? "ring-red-500/40" : "ring-white/5"
        }`}
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-medium">Control</h2>
            <p className="mt-1 text-xs text-zinc-500">
              Mode <span className="text-zinc-300">{activity.mode}</span>
              {activity.paused && " · ARIA is paused"}
              {activity.autonomy_stopped && " · automatic sending is off"}
              {activity.emergency_stop && " · EMERGENCY STOP ACTIVE"}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              disabled={busy}
              onClick={() => control(() => api.waPause(activity.paused))}
              className="flex items-center gap-2 rounded-lg bg-white/5 px-3 py-2 text-xs hover:bg-white/10 disabled:opacity-50"
            >
              {activity.paused ? (
                <>
                  <Play className="h-3.5 w-3.5" aria-hidden /> Resume ARIA
                </>
              ) : (
                <>
                  <Pause className="h-3.5 w-3.5" aria-hidden /> Pause ARIA
                </>
              )}
            </button>
            <button
              disabled={busy}
              onClick={() =>
                control(() => api.waStopAutonomy(activity.autonomy_stopped))
              }
              className="flex items-center gap-2 rounded-lg bg-white/5 px-3 py-2 text-xs hover:bg-white/10 disabled:opacity-50"
            >
              <CircleSlash className="h-3.5 w-3.5" aria-hidden />
              {activity.autonomy_stopped ? "Allow autonomy" : "Stop autonomy"}
            </button>
            <button
              disabled={busy || activity.emergency_stop}
              onClick={() => control(() => api.waEmergencyStop())}
              className="flex items-center gap-2 rounded-lg bg-red-500/15 px-3 py-2 text-xs font-medium text-red-300 ring-1 ring-red-500/40 hover:bg-red-500/25 disabled:opacity-50"
            >
              <OctagonX className="h-3.5 w-3.5" aria-hidden /> Emergency stop
            </button>
          </div>
        </div>
        {activity.emergency_stop && (
          <p className="mt-3 rounded-lg bg-red-500/10 px-3 py-2 text-xs text-red-300">
            All outward messages are blocked and anything queued was cancelled.
            Clear the stop from the WhatsApp page to resume.
          </p>
        )}
      </section>

      {/* --- Message flow --- */}
      <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat
          label="Received"
          value={activity.messages.received}
          icon={Inbox}
          hint="durably stored on arrival"
        />
        <Stat
          label="Processed"
          value={activity.messages.processed}
          icon={CheckCircle2}
          tone="good"
        />
        <Stat
          label="In progress"
          value={activity.messages.pending}
          icon={RefreshCw}
          hint={
            activity.messages.backlog_seconds > 60
              ? `oldest waiting ${Math.round(
                  activity.messages.backlog_seconds / 60,
                )}m`
              : undefined
          }
        />
        <Stat
          label="Failed"
          value={activity.messages.failed}
          icon={AlertTriangle}
          tone={activity.messages.failed > 0 ? "danger" : "default"}
          hint={activity.messages.failed > 0 ? "kept, not lost" : "none"}
        />
      </section>

      {/* --- What ARIA did on her own --- */}
      <section className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Stat
          label="Auto-answered"
          value={activity.autonomous.sent}
          icon={Bot}
          tone="good"
        />
        <Stat
          label="Awaiting you"
          value={activity.autonomous.awaiting_approval}
          icon={Hand}
          tone="warn"
        />
        <Stat label="Blocked" value={activity.autonomous.blocked} icon={Ban} />
        <Stat
          label="Unreviewed"
          value={activity.autonomous.unreviewed}
          icon={ShieldAlert}
          hint="not the same as approved"
        />
        <Stat
          label="Est. cost"
          value={`$${activity.estimated_autonomous_cost_usd.toFixed(4)}`}
          icon={Coins}
          hint="autonomy only"
        />
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* --- Risk and models --- */}
        <section className="glass rounded-xl p-4">
          <h2 className="text-sm font-medium">Risk of what she handled</h2>
          <div className="mt-3 space-y-2">
            {Object.keys(activity.risk_breakdown).length === 0 && (
              <p className="text-xs text-zinc-500">Nothing handled yet.</p>
            )}
            {Object.entries(activity.risk_breakdown).map(([level, count]) => (
              <div key={level} className="flex items-center justify-between">
                <RiskBadge level={level} />
                <span className="text-sm text-zinc-300">{count}</span>
              </div>
            ))}
          </div>
          <h3 className="mt-5 text-[11px] uppercase tracking-widest text-zinc-500">
            Models used
          </h3>
          <div className="mt-2 space-y-1">
            {Object.entries(activity.models_used).map(([model, count]) => (
              <div
                key={model}
                className="flex items-center justify-between text-xs text-zinc-400"
              >
                <span className="font-mono">{model}</span>
                <span>{count}</span>
              </div>
            ))}
          </div>
        </section>

        {/* --- Contacts with autonomy --- */}
        <section className="glass rounded-xl p-4">
          <h2 className="text-sm font-medium">Contacts with autonomy</h2>
          {activity.autonomous_contacts.length === 0 ? (
            <p className="mt-3 text-xs text-zinc-500">
              None. ARIA sends nothing automatically until you enable a contact
              explicitly on the WhatsApp page.
            </p>
          ) : (
            <ul className="mt-3 space-y-3">
              {activity.autonomous_contacts.map((c) => (
                <li key={c.id} className="rounded-lg bg-white/5 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <div>
                      <span className="text-sm text-zinc-200">{c.name}</span>
                      <span className="ml-2 text-[10px] uppercase tracking-wider text-zinc-500">
                        {c.trust_level}
                      </span>
                      {c.taken_over && (
                        <span className="ml-2 text-[10px] text-cyan-300">
                          you took over
                        </span>
                      )}
                      {c.paused && (
                        <span className="ml-2 text-[10px] text-amber-300">
                          paused
                        </span>
                      )}
                    </div>
                    <div className="flex gap-1">
                      <button
                        disabled={busy}
                        onClick={() =>
                          control(() => api.waTakeOver(c.id, c.taken_over))
                        }
                        className="rounded bg-white/5 px-2 py-1 text-[10px] hover:bg-white/10"
                      >
                        {c.taken_over ? "Hand back" : "Take over"}
                      </button>
                      <button
                        disabled={busy}
                        onClick={() =>
                          control(() => api.waPauseContact(c.id, c.paused))
                        }
                        className="rounded bg-white/5 px-2 py-1 text-[10px] hover:bg-white/10"
                      >
                        {c.paused ? "Resume" : "Pause"}
                      </button>
                    </div>
                  </div>
                  <p className="mt-2 text-[11px] text-zinc-500">
                    Allowed: {c.allowed_actions.join(", ") || "none"}
                  </p>
                  <p className="mt-1 text-[11px] text-zinc-500">
                    Voice confidence{" "}
                    <span className="text-zinc-300">
                      {(c.communication_confidence * 100).toFixed(0)}%
                    </span>
                    {c.reviewed_responses > 0 ? (
                      <>
                        {" · "}corrected{" "}
                        <span className="text-zinc-300">
                          {(c.correction_rate * 100).toFixed(0)}%
                        </span>{" "}
                        of {c.reviewed_responses} reviewed
                      </>
                    ) : (
                      " · no feedback yet"
                    )}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      {/* --- Recent autonomous responses --- */}
      <section className="glass rounded-xl p-4">
        <h2 className="text-sm font-medium">Recent autonomous responses</h2>
        <p className="mt-1 text-xs text-zinc-500">
          Every message ARIA sent on her own, with the reasons she was allowed
          to. Correcting one teaches her; ignoring one teaches her nothing.
        </p>
        {responses.length === 0 ? (
          <p className="mt-4 text-xs text-zinc-500">
            ARIA has not sent anything on her own.
          </p>
        ) : (
          <ul className="mt-4 space-y-3">
            {responses.map((r) => (
              <li key={r.id} className="rounded-lg bg-white/5 p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm text-zinc-200">{r.contact_name}</span>
                  <RiskBadge level={r.risk_level} />
                  <span className="rounded bg-white/5 px-2 py-0.5 text-[10px] text-zinc-400">
                    {r.action_type}
                  </span>
                  <span className="rounded bg-white/5 px-2 py-0.5 text-[10px] font-mono text-zinc-500">
                    {r.model}
                  </span>
                  <span
                    className={`text-[10px] ${
                      r.send_status === "sent"
                        ? "text-emerald-300"
                        : r.send_status === "blocked"
                          ? "text-red-300"
                          : "text-zinc-400"
                    }`}
                  >
                    {r.send_status}
                  </span>
                  {r.user_reaction === "none" ? (
                    <span className="text-[10px] text-amber-300">unreviewed</span>
                  ) : (
                    <span className="text-[10px] text-cyan-300">
                      you {r.user_reaction} this
                    </span>
                  )}
                </div>

                <p className="mt-2 text-xs text-zinc-500">
                  They said: <span className="text-zinc-400">{r.incoming}</span>
                </p>
                <p className="mt-1 text-sm text-zinc-200">
                  ARIA replied: {r.response}
                </p>

                <details className="mt-2">
                  <summary className="cursor-pointer text-[11px] text-zinc-500 hover:text-zinc-300">
                    Why she was allowed to
                  </summary>
                  <ul className="mt-1 space-y-0.5 pl-4 text-[11px] text-zinc-500">
                    {r.decision_reasons.map((reason, i) => (
                      <li key={i} className="list-disc">
                        {reason}
                      </li>
                    ))}
                  </ul>
                </details>

                {r.user_reaction === "none" && (
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <button
                      disabled={busy}
                      onClick={() => react(r.id, "approved")}
                      className="flex items-center gap-1 rounded bg-emerald-500/15 px-2 py-1 text-[11px] text-emerald-300 hover:bg-emerald-500/25"
                    >
                      <CheckCircle2 className="h-3 w-3" aria-hidden /> That was right
                    </button>
                    <button
                      disabled={busy}
                      onClick={() =>
                        setEditing(editing === r.id ? null : r.id)
                      }
                      className="flex items-center gap-1 rounded bg-white/5 px-2 py-1 text-[11px] hover:bg-white/10"
                    >
                      <Pencil className="h-3 w-3" aria-hidden /> Correct it
                    </button>
                    <button
                      disabled={busy}
                      onClick={() => react(r.id, "rejected")}
                      className="flex items-center gap-1 rounded bg-red-500/10 px-2 py-1 text-[11px] text-red-300 hover:bg-red-500/20"
                    >
                      <Ban className="h-3 w-3" aria-hidden /> Should not have sent
                    </button>
                  </div>
                )}

                {editing === r.id && (
                  <div className="mt-2">
                    <textarea
                      value={correction}
                      onChange={(e) => setCorrection(e.target.value)}
                      placeholder="What you would have said instead…"
                      className="w-full rounded-lg bg-black/30 p-2 text-sm text-zinc-200 outline-none ring-1 ring-white/10 focus:ring-cyan-500/40"
                      rows={2}
                    />
                    <button
                      disabled={busy || !correction.trim()}
                      onClick={() => react(r.id, "corrected", correction.trim())}
                      className="mt-2 rounded bg-cyan-500/20 px-3 py-1 text-[11px] text-cyan-200 hover:bg-cyan-500/30 disabled:opacity-40"
                    >
                      Teach her this
                    </button>
                  </div>
                )}

                {r.correction && (
                  <p className="mt-2 text-[11px] text-cyan-300">
                    You corrected it to: {r.correction}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* --- Readiness (advisory only) --- */}
        <section className="glass rounded-xl p-4">
          <h2 className="text-sm font-medium">Autonomy readiness</h2>
          <p className="mt-1 text-xs text-zinc-500">
            {readiness?.advisory}
          </p>
          <ul className="mt-3 space-y-3">
            {readiness?.contacts.map((c) => (
              <li key={c.contact_id} className="rounded-lg bg-white/5 p-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-zinc-200">{c.contact_name}</span>
                  <span className="text-sm text-zinc-300">
                    {(c.score * 100).toFixed(0)}%
                  </span>
                </div>
                <div className="mt-2 h-1 overflow-hidden rounded-full bg-white/10">
                  <div
                    className="h-full rounded-full bg-cyan-400/70"
                    style={{ width: `${Math.round(c.score * 100)}%` }}
                  />
                </div>
                {c.blocking.map((b, i) => (
                  <p key={i} className="mt-2 text-[11px] text-amber-300">
                    {b}
                  </p>
                ))}
                {c.notes.map((n, i) => (
                  <p key={i} className="mt-1 text-[11px] text-zinc-500">
                    {n}
                  </p>
                ))}
              </li>
            ))}
          </ul>
        </section>

        {/* --- Learning + errors --- */}
        <div className="space-y-6">
          <section className="glass rounded-xl p-4">
            <h2 className="text-sm font-medium">What she learned recently</h2>
            {activity.recent_learning.length === 0 ? (
              <p className="mt-3 text-xs text-zinc-500">Nothing yet.</p>
            ) : (
              <ul className="mt-3 space-y-2">
                {activity.recent_learning.map((e, i) => (
                  <li key={i} className="text-xs text-zinc-400">
                    <span className="rounded bg-white/5 px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-zinc-500">
                      {e.kind}
                    </span>{" "}
                    {e.note || (e.final ? `corrected to "${e.final}"` : "observed")}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="glass rounded-xl p-4">
            <h2 className="text-sm font-medium">Errors</h2>
            {activity.errors.length === 0 ? (
              <p className="mt-3 text-xs text-zinc-500">
                No messages have failed processing.
              </p>
            ) : (
              <ul className="mt-3 space-y-2">
                {activity.errors.map((e) => (
                  <li key={e.id} className="rounded-lg bg-red-500/5 p-2">
                    <p className="text-xs text-zinc-300">{e.body}</p>
                    <p className="mt-1 text-[11px] text-red-300">
                      {e.attempts} attempts · {e.last_error}
                    </p>
                    <button
                      disabled={busy}
                      onClick={() => control(() => api.waRetryQueued(e.id))}
                      className="mt-1 rounded bg-white/5 px-2 py-1 text-[10px] hover:bg-white/10"
                    >
                      Retry
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>
    </main>
  );
}
