/**
 * Sidebar navigation — glass rail with the ARIA reactor mark.
 *
 * Responsive: full rail with labels on md+ screens; collapses to an
 * icon-only rail on phones so the dashboard works on a small screen.
 */
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Briefcase,
  Brain,
  CalendarCheck,
  GraduationCap,
  Home,
  MessageSquare,
  MessagesSquare,
  Send,
  Settings,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";

const NAV_ITEMS: { label: string; href: string; icon: LucideIcon }[] = [
  { label: "Home", href: "/", icon: Home },
  { label: "Chat", href: "/chat", icon: MessageSquare },
  { label: "Memory", href: "/memory", icon: Brain },
  { label: "Approvals", href: "/approvals", icon: ShieldCheck },
  { label: "Messages", href: "/messages", icon: Send },
  { label: "WhatsApp", href: "/whatsapp", icon: MessagesSquare },
  { label: "Job Tracker", href: "/jobs", icon: Briefcase },
  { label: "Tasks", href: "/tasks", icon: CalendarCheck },
  { label: "Learning", href: "/learning", icon: GraduationCap },
  { label: "Settings", href: "/settings", icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="glass sticky top-0 flex h-screen w-16 shrink-0 flex-col p-3 md:w-60 md:p-4">
      {/* Brand: reactor dot + wordmark */}
      <Link href="/" className="mb-8 flex items-center gap-3 px-1 md:px-2">
        <span className="relative flex h-3.5 w-3.5 shrink-0 items-center justify-center">
          <span className="reactor absolute h-3.5 w-3.5 rounded-full bg-cyan-400/90" />
          <span className="absolute h-1.5 w-1.5 rounded-full bg-white" />
        </span>
        <span className="hidden md:block">
          <span className="block text-lg font-semibold tracking-[0.25em]">ARIA</span>
          <span className="block text-[10px] uppercase tracking-widest text-zinc-500">
            Personal AI OS
          </span>
        </span>
      </Link>

      <nav aria-label="Main navigation" className="flex flex-col gap-1">
        {NAV_ITEMS.map(({ label, href, icon: Icon }) => {
          const active = pathname === href;
          return (
            <Link
              key={href}
              href={href}
              aria-current={active ? "page" : undefined}
              title={label}
              className={`group flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm transition-colors ${
                active
                  ? "bg-cyan-400/10 font-medium text-cyan-300"
                  : "text-zinc-400 hover:bg-white/5 hover:text-zinc-100"
              }`}
            >
              <Icon
                size={17}
                strokeWidth={active ? 2.2 : 1.8}
                className={active ? "text-cyan-300" : "text-zinc-500 group-hover:text-zinc-300"}
                aria-hidden
              />
              <span className="hidden md:inline">{label}</span>
              {active && (
                <span
                  aria-hidden
                  className="ml-auto hidden h-1 w-1 rounded-full bg-cyan-400 md:block"
                />
              )}
            </Link>
          );
        })}
      </nav>

      <p className="mt-auto hidden px-2 text-[10px] text-zinc-600 md:block">
        Drafts everything. Sends nothing without you.
      </p>
    </aside>
  );
}
