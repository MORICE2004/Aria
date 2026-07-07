/**
 * Messages — draft replies and summarize conversations.
 *
 * Workflow: paste a conversation from any platform, tell ARIA what the reply
 * should achieve, get a draft in your voice. For WhatsApp/Instagram/LinkedIn
 * you copy the draft back into the app yourself (there is no safe official
 * API for personal accounts). For email, "Send as email…" hands the draft to
 * the approval queue — nothing is sent until you approve it there.
 */
"use client";

import { useState } from "react";
import { api } from "@/lib/api";

const PLATFORMS = ["whatsapp", "instagram", "linkedin", "email"] as const;

export default function MessagesPage() {
  const [platform, setPlatform] = useState<(typeof PLATFORMS)[number]>("whatsapp");
  const [conversation, setConversation] = useState("");
  const [instructions, setInstructions] = useState("");
  const [output, setOutput] = useState("");
  const [busy, setBusy] = useState<"draft" | "summary" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  // Email hand-off form state
  const [emailTo, setEmailTo] = useState("");
  const [emailSubject, setEmailSubject] = useState("");
  const [queued, setQueued] = useState(false);

  async function run(kind: "draft" | "summary") {
    if (!conversation.trim()) return;
    setBusy(kind);
    setError(null);
    setOutput("");
    setQueued(false);
    try {
      const result =
        kind === "draft"
          ? await api.draftReply(platform, conversation, instructions)
          : await api.summarize(conversation);
      setOutput(result.text);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function copy() {
    await navigator.clipboard.writeText(output);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  async function queueEmail(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.requestEmailSend(emailTo, emailSubject, output);
      setQueued(true);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <div className="mx-auto max-w-3xl">
      <h2 className="mb-1 text-2xl font-semibold">Messages</h2>
      <p className="mb-6 text-sm text-zinc-400">
        Paste a conversation, get a reply drafted in your voice. ARIA never
        sends anything — you copy the draft, or route email through Approvals.
      </p>

      <div className="mb-3 flex gap-2">
        {PLATFORMS.map((p) => (
          <button
            key={p}
            onClick={() => setPlatform(p)}
            className={`rounded-md px-3 py-1.5 text-sm capitalize ${
              platform === p
                ? "bg-indigo-600 text-white"
                : "border border-zinc-700 text-zinc-400 hover:text-white"
            }`}
          >
            {p}
          </button>
        ))}
      </div>

      <textarea
        value={conversation}
        onChange={(e) => setConversation(e.target.value)}
        placeholder="Paste the conversation here…"
        aria-label="Conversation"
        rows={8}
        className="mb-3 w-full rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm outline-none focus:border-zinc-500"
      />
      <input
        value={instructions}
        onChange={(e) => setInstructions(e.target.value)}
        placeholder="What should the reply achieve? (e.g. 'politely decline, suggest next week')"
        aria-label="Instructions"
        className="mb-3 w-full rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm outline-none focus:border-zinc-500"
      />

      <div className="mb-6 flex gap-2">
        <button
          onClick={() => run("draft")}
          disabled={busy !== null || !conversation.trim()}
          className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-40"
        >
          {busy === "draft" ? "Drafting…" : "Draft reply"}
        </button>
        <button
          onClick={() => run("summary")}
          disabled={busy !== null || !conversation.trim()}
          className="rounded-md border border-zinc-700 px-4 py-2 text-sm text-zinc-300 hover:text-white disabled:opacity-40"
        >
          {busy === "summary" ? "Summarizing…" : "Summarize"}
        </button>
      </div>

      {error && (
        <p role="alert" className="mb-4 text-sm text-red-400">
          {error}
        </p>
      )}

      {output && (
        <section className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-sm font-medium text-zinc-300">Draft</h3>
            <button
              onClick={copy}
              className="rounded-md border border-zinc-700 px-3 py-1 text-xs text-zinc-300 hover:text-white"
            >
              {copied ? "Copied ✓" : "Copy"}
            </button>
          </div>
          <p className="whitespace-pre-wrap text-sm text-zinc-100">{output}</p>

          {platform === "email" && !queued && (
            <form onSubmit={queueEmail} className="mt-4 space-y-2 border-t border-zinc-800 pt-3">
              <p className="text-xs text-zinc-500">
                Send as email — goes to the Approvals queue, not directly out.
              </p>
              <div className="flex gap-2">
                <input
                  value={emailTo}
                  onChange={(e) => setEmailTo(e.target.value)}
                  placeholder="to@example.com"
                  aria-label="Recipient"
                  type="email"
                  required
                  className="flex-1 rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm outline-none focus:border-zinc-500"
                />
                <input
                  value={emailSubject}
                  onChange={(e) => setEmailSubject(e.target.value)}
                  placeholder="Subject"
                  aria-label="Subject"
                  required
                  className="flex-1 rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm outline-none focus:border-zinc-500"
                />
                <button className="rounded-md bg-emerald-700 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-600">
                  Queue for approval
                </button>
              </div>
            </form>
          )}
          {queued && (
            <p className="mt-3 text-sm text-emerald-400">
              Queued ✓ — review it on the{" "}
              <a href="/approvals" className="underline">
                Approvals page
              </a>
              . Nothing is sent until you approve it there.
            </p>
          )}
        </section>
      )}
    </div>
  );
}
