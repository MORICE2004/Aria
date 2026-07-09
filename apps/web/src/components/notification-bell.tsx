/**
 * Notification bell — ARIA's "who needs you" panel.
 *
 * Polls /notifications every 60s. Aggregates: unread emails (who wrote,
 * about what), actions awaiting approval, and tasks due/overdue. Fires a
 * browser notification when NEW items appear (permission asked on first
 * open, never on page load — that's how permission prompts get denied).
 */
"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Bell, Mail, ShieldCheck, CalendarClock } from "lucide-react";
import { api, type Notifications } from "@/lib/api";

const POLL_MS = 60_000;

export function NotificationBell() {
  const [data, setData] = useState<Notifications | null>(null);
  const [open, setOpen] = useState(false);
  // Remember what we've already notified about, so we only alert on NEW items.
  const seen = useRef<Set<string>>(new Set());
  const firstLoad = useRef(true);

  const poll = useCallback(async () => {
    try {
      const next = await api.getNotifications();
      setData(next);

      const keys = [
        ...(next.unread_emails ?? []).map((e) => `mail:${e.sender}:${e.subject}`),
        ...next.due_tasks.map((t) => `task:${t.id}`),
      ];
      if (!firstLoad.current && Notification.permission === "granted") {
        for (const key of keys) {
          if (!seen.current.has(key)) {
            const body = key.startsWith("mail:")
              ? `New email — ${key.slice(5)}`
              : `Task due — ${next.due_tasks.find((t) => `task:${t.id}` === key)?.title}`;
            new Notification("ARIA", { body, icon: "/icon.svg" });
          }
        }
      }
      seen.current = new Set(keys);
      firstLoad.current = false;
    } catch {
      /* API offline — the panel simply shows nothing new */
    }
  }, []);

  useEffect(() => {
    const first = setTimeout(poll, 0); // deferred initial poll
    const timer = setInterval(poll, POLL_MS);
    return () => {
      clearTimeout(first);
      clearInterval(timer);
    };
  }, [poll]);

  const count =
    (data?.pending_approvals ?? 0) +
    (data?.due_tasks.length ?? 0) +
    (data?.unread_emails?.length ?? 0);

  function toggle() {
    if (!open && "Notification" in window && Notification.permission === "default") {
      Notification.requestPermission();
    }
    setOpen(!open);
  }

  return (
    <div className="fixed right-4 top-4 z-50">
      <button
        onClick={toggle}
        aria-label={`Notifications${count ? ` (${count})` : ""}`}
        className="glass relative rounded-full p-2.5 text-zinc-300 hover:text-white"
      >
        <Bell size={18} aria-hidden />
        {count > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-cyan-400 px-1 text-[10px] font-bold text-cyan-950">
            {count > 9 ? "9+" : count}
          </span>
        )}
      </button>

      {open && data && (
        <div className="glass mt-2 max-h-[70vh] w-80 overflow-y-auto rounded-xl p-3 text-sm shadow-2xl">
          {data.pending_approvals > 0 && (
            <Link
              href="/approvals"
              onClick={() => setOpen(false)}
              className="mb-1 flex items-center gap-2 rounded-lg p-2 hover:bg-white/5"
            >
              <ShieldCheck size={15} className="shrink-0 text-amber-400" aria-hidden />
              <span>
                <strong>{data.pending_approvals}</strong> action
                {data.pending_approvals > 1 ? "s" : ""} awaiting your approval
              </span>
            </Link>
          )}

          {data.due_tasks.map((t) => (
            <Link
              key={t.id}
              href="/tasks"
              onClick={() => setOpen(false)}
              className="mb-1 flex items-center gap-2 rounded-lg p-2 hover:bg-white/5"
            >
              <CalendarClock
                size={15}
                className={`shrink-0 ${t.overdue ? "text-red-400" : "text-amber-400"}`}
                aria-hidden
              />
              <span className={t.overdue ? "text-red-300" : ""}>
                {t.overdue ? "Overdue: " : "Due today: "}
                {t.title}
              </span>
            </Link>
          ))}

          {data.unread_emails?.map((m, i) => (
            <div key={i} className="mb-1 rounded-lg p-2 hover:bg-white/5">
              <p className="flex items-center gap-2">
                <Mail size={15} className="shrink-0 text-cyan-400" aria-hidden />
                <span className="truncate font-medium">{m.sender}</span>
              </p>
              <p className="mt-0.5 truncate pl-6 text-zinc-400">{m.subject}</p>
              <div className="pl-6">
                <Link
                  href="/messages"
                  onClick={() => {
                    sessionStorage.setItem(
                      "aria_prefill",
                      JSON.stringify({
                        platform: "email",
                        conversation: `From: ${m.sender}\nSubject: ${m.subject}\n\n${m.snippet}`,
                      }),
                    );
                    setOpen(false);
                  }}
                  className="text-xs text-cyan-400 hover:underline"
                >
                  Draft a reply →
                </Link>
              </div>
            </div>
          ))}

          {data.unread_emails === null && (
            <p className="rounded-lg p-2 text-xs text-zinc-500">
              Email notifications off — set IMAP_HOST in .env to see who wrote.
            </p>
          )}

          {count === 0 && (
            <p className="rounded-lg p-2 text-zinc-500">
              All clear — nothing needs you right now.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
