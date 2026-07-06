/**
 * Sidebar navigation.
 *
 * One entry per major dashboard area. Most link targets are placeholders
 * until their phase is built — the map below is the roadmap made visible.
 * "use client" because usePathname (highlighting the active link) only
 * works in a client component.
 */
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/** Nav items: label, route, and the phase that will make them functional. */
const NAV_ITEMS = [
  { label: "Home", href: "/", phase: 0 },
  { label: "Chat", href: "/chat", phase: 1 },
  { label: "Memory", href: "/memory", phase: 2 },
  { label: "Approvals", href: "/approvals", phase: 3 },
  { label: "Messages", href: "/messages", phase: 4 },
  { label: "Job Tracker", href: "/jobs", phase: 5 },
  { label: "Tasks & Calendar", href: "/tasks", phase: 6 },
  { label: "Learning", href: "/learning", phase: 7 },
  { label: "Settings", href: "/settings", phase: 1 },
] as const;

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="flex w-60 flex-col border-r border-zinc-800 bg-zinc-900 p-4">
      <div className="mb-8 px-2">
        <h1 className="text-xl font-bold tracking-tight">ARIA</h1>
        <p className="text-xs text-zinc-400">Personal AI Assistant</p>
      </div>

      <nav aria-label="Main navigation" className="flex flex-col gap-1">
        {NAV_ITEMS.map((item) => {
          const active = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={`rounded-md px-3 py-2 text-sm transition-colors ${
                active
                  ? "bg-zinc-800 font-medium text-white"
                  : "text-zinc-400 hover:bg-zinc-800/60 hover:text-zinc-100"
              }`}
            >
              {item.label}
            </Link>
          );
        })}
      </nav>

      <p className="mt-auto px-2 text-[10px] text-zinc-600">
        Phase 0 — foundation
      </p>
    </aside>
  );
}
