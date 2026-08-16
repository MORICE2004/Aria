/**
 * WhatsApp control center.
 *
 * The page makes four things impossible to miss — the current autonomy level,
 * the emergency stop, the per-contact trust that caps what ARIA may ever do,
 * and (new) exactly which kinds of message each contact has been cleared for.
 *
 * The per-contact policy editor is deliberately explicit rather than a single
 * "autonomous" switch: MORICE grants ARIA named categories for named people,
 * so what she is allowed to do is always readable at a glance instead of
 * inferred from a trust level.
 */
"use client";

import { useCallback, useEffect, useState } from "react";
import { ShieldAlert, Eye } from "lucide-react";
import {
  api,
  type WaContact,
  type WaObservation,
  type WaOverview,
} from "@/lib/api";
import { DraftReview } from "@/components/draft-review";

const MODES = [
  "observe",
  "suggest",
  "supervised",
  "limited_autonomy",
  "full_autonomy",
] as const;
const TRUST = ["unknown", "low", "trusted", "high", "never_autonomous"] as const;

/** Categories a contact can be cleared for. Mirrors risk.ACTION_TYPES; the
 *  sensitive ones are absent on purpose — they can never be autonomous, so
 *  offering a checkbox for them would be a lie. */
const GRANTABLE = [
  "greeting",
  "routine_reply",
  "scheduling",
  "status_update",
  "documents",
  "commitment",
] as const;

const MODE_BLURB: Record<string, string> = {
  observe: "Watches and learns. Never responds.",
  suggest: "Prepares drafts for your review.",
  supervised: "May send only after you confirm each message.",
  limited_autonomy:
    "Automatically handles low-risk conversations with contacts you have explicitly enabled.",
  full_autonomy:
    "Handles a broader range of conversations per each contact's policy. High-risk still comes to you.",
};

export default function WhatsAppPage() {
  const [data, setData] = useState<WaOverview | null>(null);
  const [obs, setObs] = useState<WaObservation | null>(null);
  const [simBody, setSimBody] = useState("");
  const [simHandle, setSimHandle] = useState("demo@s.whatsapp.net");
  const [simName, setSimName] = useState("Demo Contact");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(
    () => api.waOverview().then(setData).catch((e: Error) => setError(e.message)),
    [],
  );

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function setMode(mode: string) {
    setError(null);
    try {
      await api.waSetAutonomy({ mode });
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function simulate(e: React.FormEvent) {
    e.preventDefault();
    if (!simBody.trim()) return;
    setBusy(true);
    setError(null);
    try {
      setObs(await api.waSimulate(simHandle.trim(), simName.trim(), simBody.trim()));
      setSimBody("");
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const stopped = data?.emergency_stop ?? false;

  return (
    <div className="mx-auto max-w-4xl">
      <h2 className="mb-1 text-2xl font-semibold">WhatsApp</h2>
      <p className="mb-6 text-sm text-zinc-400">
        ARIA is in observe mode: she reads and learns, and has no ability to
        send. Raising autonomy is always deliberate and always logged.
      </p>

      {error && <p role="alert" className="mb-4 text-sm text-red-400">{error}</p>}

      {/* Status + kill switch */}
      <section
        className={`glass mb-6 rounded-xl p-5 ${stopped ? "border-red-500/50" : ""}`}
      >
        <div className="flex flex-wrap items-center gap-3">
          <Eye size={18} className="text-cyan-400" aria-hidden />
          <div className="flex-1">
            <p className="text-sm">
              Autonomy level:{" "}
              <strong className="uppercase tracking-wide text-cyan-300">
                {data?.mode ?? "…"}
              </strong>
            </p>
            <p className="text-xs text-zinc-500">
              {MODE_BLURB[data?.mode ?? "observe"]}
            </p>
          </div>
          <button
            onClick={async () => {
              if (stopped) {
                await api.waSetAutonomy({ emergency_stop: false });
              } else {
                await api.waEmergencyStop();
              }
              await refresh();
            }}
            className={`flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium ${
              stopped
                ? "bg-zinc-100 text-zinc-900 hover:bg-white"
                : "bg-red-600 text-white hover:bg-red-500"
            }`}
          >
            <ShieldAlert size={15} aria-hidden />
            {stopped ? "Clear emergency stop" : "Emergency stop"}
          </button>
        </div>

        {stopped && (
          <p className="mt-3 rounded-lg bg-red-500/10 px-3 py-2 text-xs text-red-300">
            Emergency stop is active. All external action is blocked and the
            mode is forced to observe.
          </p>
        )}

        <div className="mt-4 flex flex-wrap gap-2">
          {MODES.map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              disabled={stopped}
              title={MODE_BLURB[m]}
              className={`rounded-md px-3 py-1.5 text-xs capitalize disabled:opacity-30 ${
                data?.mode === m
                  ? "bg-cyan-600 font-medium text-white"
                  : "border border-zinc-700 text-zinc-400 hover:text-white"
              }`}
            >
              {m}
            </button>
          ))}
        </div>

        {data && !data.channel_linked && (
          <p className="mt-4 border-t border-white/10 pt-3 text-xs text-amber-300/80">
            No real WhatsApp account is linked yet — everything below is
            simulated. Link one with{" "}
            <code className="rounded bg-white/5 px-1.5 py-0.5">
              openclaw channels login --channel whatsapp
            </code>
          </p>
        )}
      </section>

      {/* Drafts awaiting review */}
      <DraftReview />

      {/* Simulator */}
      <section className="glass mb-6 rounded-xl p-5">
        <h3 className="mb-1 text-sm font-medium">Conversation simulator</h3>
        <p className="mb-3 text-xs text-zinc-500">
          Feed ARIA a message as if it arrived on WhatsApp. This is how observe
          mode is tested before any real account is connected.
        </p>
        <form onSubmit={simulate} className="space-y-2">
          <div className="flex gap-2">
            <input
              value={simName}
              onChange={(e) => setSimName(e.target.value)}
              aria-label="Sender name"
              placeholder="Sender name"
              className="flex-1 rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm outline-none focus:border-zinc-500"
            />
            <input
              value={simHandle}
              onChange={(e) => setSimHandle(e.target.value)}
              aria-label="Sender handle"
              placeholder="handle@s.whatsapp.net"
              className="flex-1 rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm outline-none focus:border-zinc-500"
            />
          </div>
          <textarea
            value={simBody}
            onChange={(e) => setSimBody(e.target.value)}
            rows={3}
            aria-label="Message body"
            placeholder="Type the incoming message…"
            className="w-full rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm outline-none focus:border-zinc-500"
          />
          <button
            disabled={busy || !simBody.trim()}
            className="rounded-md bg-cyan-600 px-4 py-2 text-sm font-medium text-white hover:bg-cyan-500 disabled:opacity-40"
          >
            {busy ? "Observing…" : "Send to ARIA"}
          </button>
        </form>

        {obs && (
          <div className="mt-4 space-y-2 border-t border-white/10 pt-4 text-sm">
            <p>
              <span className="text-zinc-500">Intent:</span>{" "}
              {obs.intent ?? <em className="text-zinc-600">not classified</em>}
            </p>
            <p className="flex flex-wrap items-center gap-2">
              <span className="text-zinc-500">Flags:</span>
              {obs.sensitive.length ? (
                obs.sensitive.map((s) => (
                  <span
                    key={s}
                    className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] uppercase text-amber-300"
                  >
                    {s}
                  </span>
                ))
              ) : (
                <span className="text-zinc-600">none</span>
              )}
              {obs.urgency && (
                <span className="text-xs text-zinc-500">urgency: {obs.urgency}</span>
              )}
              {obs.language && (
                <span className="text-xs text-zinc-500">lang: {obs.language}</span>
              )}
            </p>
            <p>
              <span className="text-zinc-500">ARIA may:</span>{" "}
              <strong className="text-cyan-300">{obs.effective_mode}</strong>{" "}
              <span className="text-xs text-zinc-500">({obs.mode_reason})</span>
            </p>
            <p className="text-emerald-400">
              Nothing was sent{obs.draft ? " — draft prepared for review." : "."}
            </p>
          </div>
        )}
      </section>

      {/* Contacts + trust */}
      <h3 className="mb-2 text-sm font-medium text-zinc-300">
        Contacts &amp; trust levels
      </h3>
      <ul className="space-y-2">
        {data?.contacts.map((c) => (
          <li key={c.id} className="glass rounded-xl p-4">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium">{c.name}</span>
              <span className="text-xs text-zinc-500">{c.handle}</span>
              <span className="ml-auto text-xs text-zinc-500">
                {c.message_count} observed
              </span>
            </div>
            <p className="mt-1 text-xs text-zinc-500">
              ARIA may: <strong className="text-zinc-300">{c.effective_mode}</strong> —{" "}
              {c.mode_reason}
            </p>
            <div className="mt-2 flex flex-wrap gap-1">
              {TRUST.map((t) => (
                <button
                  key={t}
                  onClick={() => api.waSetTrust(c.id, t).then(refresh)}
                  className={`rounded px-1.5 py-0.5 text-[10px] ${
                    c.trust_level === t
                      ? "bg-white/10 font-semibold text-cyan-300"
                      : "text-zinc-600 hover:text-zinc-300"
                  }`}
                >
                  {t.replace("_", " ")}
                </button>
              ))}
            </div>

            <ContactPolicy contact={c} onChange={refresh} onError={setError} />
          </li>
        ))}
        {data?.contacts.length === 0 && (
          <p className="text-sm text-zinc-500">
            No contacts observed yet — simulate a message above.
          </p>
        )}
      </ul>
    </div>
  );
}

/**
 * Per-contact autonomy policy.
 *
 * Collapsed by default: most contacts will never be autonomous, and a wall of
 * checkboxes on every row would make the ones that ARE autonomous harder to
 * spot, not easier.
 */
function ContactPolicy({
  contact,
  onChange,
  onError,
}: {
  contact: WaContact & { message_count?: number };
  onChange: () => void;
  onError: (message: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const allowed = contact.allowed_actions ?? [];

  async function patch(policy: Parameters<typeof api.waSetContactPolicy>[1]) {
    setBusy(true);
    try {
      await api.waSetContactPolicy(contact.id, policy);
      onChange();
    } catch (err) {
      // Surfaces the API's refusal verbatim — e.g. "trust level does not
      // permit autonomy". A rejected policy change must say why.
      onError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function toggle(action: string) {
    const next = allowed.includes(action)
      ? allowed.filter((a) => a !== action)
      : [...allowed, action];
    patch({ allowed_actions: next });
  }

  return (
    <div className="mt-3 border-t border-white/5 pt-2">
      <button
        onClick={() => setOpen(!open)}
        className="text-[11px] text-zinc-500 hover:text-zinc-300"
      >
        {open ? "Hide" : "Autonomy policy"}
        {contact.autonomy_enabled && (
          <span className="ml-2 rounded bg-cyan-500/15 px-1.5 py-0.5 text-[10px] text-cyan-300">
            autonomous
          </span>
        )}
        {contact.paused && (
          <span className="ml-2 text-[10px] text-amber-300">paused</span>
        )}
        {contact.taken_over && (
          <span className="ml-2 text-[10px] text-cyan-300">you took over</span>
        )}
      </button>

      {open && (
        <div className="mt-2 space-y-3">
          <label className="flex items-center gap-2 text-xs text-zinc-300">
            <input
              type="checkbox"
              disabled={busy}
              checked={contact.autonomy_enabled}
              onChange={(e) => patch({ autonomy_enabled: e.target.checked })}
              className="accent-cyan-500"
            />
            ARIA may reply to {contact.name} without asking me
          </label>

          <div>
            <p className="text-[11px] text-zinc-500">
              Only for these kinds of message:
            </p>
            <div className="mt-1 flex flex-wrap gap-1">
              {GRANTABLE.map((action) => (
                <button
                  key={action}
                  disabled={busy}
                  onClick={() => toggle(action)}
                  className={`rounded px-2 py-0.5 text-[10px] ${
                    allowed.includes(action)
                      ? "bg-cyan-500/15 text-cyan-300"
                      : "bg-white/5 text-zinc-500 hover:text-zinc-300"
                  }`}
                >
                  {action.replace("_", " ")}
                </button>
              ))}
            </div>
          </div>

          <p className="rounded-lg bg-white/5 px-2 py-1.5 text-[10px] leading-relaxed text-zinc-500">
            Never autonomous, for anyone, whatever is selected above: money,
            employment, legal matters, sensitive personal information,
            relationship-defining messages, and anything that reads as an
            attempt to give ARIA instructions. Those always come to you.
          </p>

          <div className="flex gap-2">
            <button
              disabled={busy}
              onClick={() =>
                api.waPauseContact(contact.id, contact.paused).then(onChange)
              }
              className="rounded bg-white/5 px-2 py-1 text-[10px] hover:bg-white/10"
            >
              {contact.paused ? "Resume ARIA here" : "Pause ARIA here"}
            </button>
            <button
              disabled={busy}
              onClick={() =>
                api.waTakeOver(contact.id, contact.taken_over).then(onChange)
              }
              className="rounded bg-white/5 px-2 py-1 text-[10px] hover:bg-white/10"
            >
              {contact.taken_over ? "Hand back to ARIA" : "Take over"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
