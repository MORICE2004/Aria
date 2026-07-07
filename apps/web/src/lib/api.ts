/**
 * API client — the only file that knows how to talk to the backend.
 * Components import these functions instead of calling fetch() themselves,
 * so URLs, error handling, and (later) auth headers live in one place.
 */

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Conversation = { id: string; title: string };
export type Message = { id: string; role: "user" | "assistant"; content: string };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) throw new Error(`API error ${res.status} on ${path}`);
  // 204 No Content has no body to parse.
  return res.status === 204 ? (undefined as T) : res.json();
}

export type MemoryItem = {
  id: string;
  title: string;
  kind: "note" | "document" | "fact" | "style";
  content: string;
};
export type MemoryHit = MemoryItem & { item_id: string; score: number };

export const api = {
  listMemories: () => request<MemoryItem[]>("/memory"),
  addMemory: (m: Pick<MemoryItem, "title" | "content" | "kind">) =>
    request<MemoryItem>("/memory", { method: "POST", body: JSON.stringify(m) }),
  deleteMemory: (id: string) => request<void>(`/memory/${id}`, { method: "DELETE" }),
  searchMemories: (q: string) =>
    request<MemoryHit[]>(`/memory/search?q=${encodeURIComponent(q)}`),

  listConversations: () => request<Conversation[]>("/conversations"),
  createConversation: () => request<Conversation>("/conversations", { method: "POST" }),
  deleteConversation: (id: string) =>
    request<void>(`/conversations/${id}`, { method: "DELETE" }),
  listMessages: (id: string) => request<Message[]>(`/conversations/${id}/messages`),

  /**
   * Send a message and stream the reply. Calls `onChunk` for every piece of
   * text as the model generates it, so the UI can render words live.
   */
  async sendMessage(
    conversationId: string,
    content: string,
    onChunk: (text: string) => void,
  ): Promise<void> {
    const res = await fetch(`${API_URL}/conversations/${conversationId}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    });
    if (!res.ok || !res.body) throw new Error(`API error ${res.status}`);

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    // Read the response body chunk by chunk until the model finishes.
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      onChunk(decoder.decode(value, { stream: true }));
    }
  },
};
