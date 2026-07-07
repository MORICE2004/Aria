/**
 * Chat page — conversation list on the left, message thread on the right.
 *
 * Streaming works by appending each text chunk to the last assistant message
 * in state as it arrives, so the reply "types itself" in real time.
 */
"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Conversation, type Message } from "@/lib/api";

export default function ChatPage() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Load the conversation list once on mount.
  useEffect(() => {
    api.listConversations().then(setConversations).catch((e: Error) => setError(e.message));
  }, []);

  // Load messages whenever the selected conversation changes.
  useEffect(() => {
    if (!activeId) return;
    api.listMessages(activeId).then(setMessages).catch((e: Error) => setError(e.message));
  }, [activeId]);

  // Keep the newest message in view while streaming.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const newConversation = useCallback(async () => {
    const conversation = await api.createConversation();
    setConversations((prev) => [conversation, ...prev]);
    setActiveId(conversation.id);
    setMessages([]);
  }, []);

  async function send() {
    const content = input.trim();
    if (!content || busy) return;

    // Auto-create a conversation on the very first message.
    let conversationId = activeId;
    if (!conversationId) {
      const conversation = await api.createConversation();
      setConversations((prev) => [conversation, ...prev]);
      setActiveId(conversation.id);
      conversationId = conversation.id;
    }

    setInput("");
    setBusy(true);
    setError(null);
    // Optimistically show the user message and an empty assistant bubble.
    setMessages((prev) => [
      ...prev,
      { id: `tmp-user-${Date.now()}`, role: "user", content },
      { id: `tmp-assistant-${Date.now()}`, role: "assistant", content: "" },
    ]);

    try {
      await api.sendMessage(conversationId, content, (chunk) => {
        setMessages((prev) => {
          const next = [...prev];
          const last = next[next.length - 1];
          next[next.length - 1] = { ...last, content: last.content + chunk };
          return next;
        });
      });
      // Refresh the sidebar so the auto-generated title appears.
      api.listConversations().then(setConversations).catch(() => {});
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex h-[calc(100vh-4rem)] gap-4">
      {/* Conversation list */}
      <aside className="flex w-64 flex-col rounded-lg border border-zinc-800 bg-zinc-900">
        <div className="p-3">
          <button
            onClick={newConversation}
            className="w-full rounded-md bg-zinc-100 px-3 py-2 text-sm font-medium text-zinc-900 transition-colors hover:bg-white"
          >
            + New chat
          </button>
        </div>
        <nav aria-label="Conversations" className="flex-1 overflow-y-auto px-2 pb-2">
          {conversations.map((c) => (
            <button
              key={c.id}
              onClick={() => setActiveId(c.id)}
              className={`mb-1 w-full truncate rounded-md px-3 py-2 text-left text-sm ${
                c.id === activeId
                  ? "bg-zinc-800 text-white"
                  : "text-zinc-400 hover:bg-zinc-800/60"
              }`}
            >
              {c.title}
            </button>
          ))}
        </nav>
      </aside>

      {/* Message thread */}
      <section className="flex flex-1 flex-col rounded-lg border border-zinc-800 bg-zinc-900">
        <div className="flex-1 space-y-4 overflow-y-auto p-4">
          {messages.length === 0 && (
            <p className="mt-16 text-center text-sm text-zinc-500">
              Say hello — ARIA is listening.
            </p>
          )}
          {messages.map((m) => (
            <div
              key={m.id}
              className={`max-w-[80%] whitespace-pre-wrap rounded-lg px-4 py-2 text-sm ${
                m.role === "user"
                  ? "ml-auto bg-indigo-600 text-white"
                  : "bg-zinc-800 text-zinc-100"
              }`}
            >
              {m.content || <span className="animate-pulse">…</span>}
            </div>
          ))}
          <div ref={bottomRef} />
        </div>

        {error && (
          <p role="alert" className="px-4 pb-2 text-xs text-red-400">
            {error}
          </p>
        )}

        <form
          onSubmit={(e) => {
            e.preventDefault();
            send();
          }}
          className="flex gap-2 border-t border-zinc-800 p-3"
        >
          <label htmlFor="chat-input" className="sr-only">
            Message ARIA
          </label>
          <input
            id="chat-input"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Message ARIA…"
            autoComplete="off"
            className="flex-1 rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm outline-none focus:border-zinc-500"
          />
          <button
            type="submit"
            disabled={busy || !input.trim()}
            className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-indigo-500 disabled:opacity-40"
          >
            {busy ? "…" : "Send"}
          </button>
        </form>
      </section>
    </div>
  );
}
