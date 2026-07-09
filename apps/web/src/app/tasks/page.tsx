/**
 * Tasks — tasks, reminders, deadlines, and interview dates.
 *
 * Open items are grouped by urgency (Overdue / Today / Upcoming / No date);
 * completed ones collapse into a Done section. All grouping is client-side —
 * the API returns open items already sorted by due date.
 */
"use client";

import { useEffect, useState } from "react";
import { api, type Task } from "@/lib/api";

const KINDS = ["task", "reminder", "deadline", "interview"] as const;

const KIND_BADGE: Record<(typeof KINDS)[number], string> = {
  task: "bg-zinc-700",
  reminder: "bg-sky-800",
  deadline: "bg-red-900",
  interview: "bg-purple-900",
};

function groupOf(task: Task): "overdue" | "today" | "upcoming" | "nodate" {
  if (!task.due_at) return "nodate";
  const due = new Date(task.due_at);
  const now = new Date();
  if (due < now) return "overdue";
  return due.toDateString() === now.toDateString() ? "today" : "upcoming";
}

const GROUPS: { key: ReturnType<typeof groupOf>; label: string; accent: string }[] = [
  { key: "overdue", label: "Overdue", accent: "text-red-400" },
  { key: "today", label: "Today", accent: "text-amber-400" },
  { key: "upcoming", label: "Upcoming", accent: "text-zinc-300" },
  { key: "nodate", label: "No date", accent: "text-zinc-500" },
];

export default function TasksPage() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState<(typeof KINDS)[number]>("task");
  const [due, setDue] = useState(""); // datetime-local value
  const [showDone, setShowDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = () =>
    api.listTasks().then(setTasks).catch((e: Error) => setError(e.message));

  useEffect(() => {
    refresh();
  }, []);

  async function add(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim()) return;
    // datetime-local gives local time; toISOString converts to UTC for the API.
    await api.addTask({
      title: title.trim(),
      kind,
      due_at: due ? new Date(due).toISOString() : null,
    });
    setTitle("");
    setDue("");
    await refresh();
  }

  const open = tasks.filter((t) => t.status === "open");
  const done = tasks.filter((t) => t.status === "done");

  function TaskRow({ task }: { task: Task }) {
    return (
      <li className="flex items-center gap-3 rounded-lg border border-zinc-800 bg-zinc-900 px-4 py-2.5">
        <input
          type="checkbox"
          checked={task.status === "done"}
          onChange={() =>
            api
              .updateTask(task.id, { status: task.status === "done" ? "open" : "done" })
              .then(refresh)
          }
          aria-label={`Mark "${task.title}" ${task.status === "done" ? "open" : "done"}`}
          className="h-4 w-4 accent-indigo-600"
        />
        <span
          className={`flex-1 text-sm ${
            task.status === "done" ? "text-zinc-500 line-through" : ""
          }`}
        >
          {task.title}
        </span>
        <span
          className={`rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-zinc-300 ${KIND_BADGE[task.kind]}`}
        >
          {task.kind}
        </span>
        {task.due_at && (
          <span className="text-xs text-zinc-500">
            {new Date(task.due_at).toLocaleString([], {
              month: "short",
              day: "numeric",
              hour: "2-digit",
              minute: "2-digit",
            })}
          </span>
        )}
        <button
          onClick={() => api.deleteTask(task.id).then(refresh)}
          className="text-xs text-zinc-600 hover:text-red-400"
          aria-label={`Delete "${task.title}"`}
        >
          ✕
        </button>
      </li>
    );
  }

  return (
    <div className="mx-auto max-w-3xl">
      <h2 className="mb-1 text-2xl font-semibold">Tasks & Deadlines</h2>
      <p className="mb-6 text-sm text-zinc-400">
        Tasks, reminders, deadlines, and interview dates — grouped by urgency.
      </p>

      {error && (
        <p role="alert" className="mb-4 text-sm text-red-400">{error}</p>
      )}

      <form onSubmit={add} className="mb-8 flex gap-2">
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="What needs doing?"
          aria-label="Task title"
          className="flex-1 rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm outline-none focus:border-zinc-500"
        />
        <select
          value={kind}
          onChange={(e) => setKind(e.target.value as (typeof KINDS)[number])}
          aria-label="Kind"
          className="rounded-md border border-zinc-700 bg-zinc-950 px-2 py-2 text-sm capitalize"
        >
          {KINDS.map((k) => (
            <option key={k}>{k}</option>
          ))}
        </select>
        <input
          type="datetime-local"
          value={due}
          onChange={(e) => setDue(e.target.value)}
          aria-label="Due date"
          className="rounded-md border border-zinc-700 bg-zinc-950 px-2 py-2 text-sm"
        />
        <button className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500">
          Add
        </button>
      </form>

      {GROUPS.map(({ key, label, accent }) => {
        const items = open.filter((t) => groupOf(t) === key);
        if (items.length === 0) return null;
        return (
          <section key={key} className="mb-6">
            <h3 className={`mb-2 text-sm font-medium ${accent}`}>
              {label} ({items.length})
            </h3>
            <ul className="space-y-2">
              {items.map((t) => (
                <TaskRow key={t.id} task={t} />
              ))}
            </ul>
          </section>
        );
      })}
      {open.length === 0 && (
        <p className="mb-6 text-sm text-zinc-500">Nothing open — enjoy the calm.</p>
      )}

      {done.length > 0 && (
        <section>
          <button
            onClick={() => setShowDone(!showDone)}
            className="mb-2 text-sm text-zinc-500 hover:text-zinc-300"
          >
            {showDone ? "▾" : "▸"} Done ({done.length})
          </button>
          {showDone && (
            <ul className="space-y-2">
              {done.map((t) => (
                <TaskRow key={t.id} task={t} />
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}
