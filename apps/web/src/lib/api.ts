/**
 * API client — the only file that knows how to talk to the backend.
 * Components import these functions instead of calling fetch() themselves,
 * so URLs, error handling, and (later) auth headers live in one place.
 */

/**
 * Where the API lives. Defaults to port 8000 on WHATEVER host served this
 * page — so opening the dashboard from a phone at http://192.168.x.x:3000
 * automatically talks to the API on the same machine. Override with
 * NEXT_PUBLIC_API_URL when they're on different hosts.
 */
export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ??
  (typeof window !== "undefined"
    ? `http://${window.location.hostname}:8000`
    : "http://localhost:8000");

export type Conversation = { id: string; title: string };
export type Message = { id: string; role: "user" | "assistant"; content: string };

/** The login token lives in localStorage; every request attaches it. */
function authHeaders(): Record<string, string> {
  const token =
    typeof window !== "undefined" ? localStorage.getItem("aria_token") : null;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...authHeaders(), ...init?.headers },
  });
  if (res.status === 401 && typeof window !== "undefined") {
    window.location.href = "/login"; // token missing/expired — go log in
  }
  if (!res.ok) {
    // Surface the API's explanation when it has one (e.g. "SMTP not configured").
    const detail = await res.json().then((b) => b.detail).catch(() => null);
    throw new Error(detail || `API error ${res.status} on ${path}`);
  }
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

export type ActionRequest = {
  id: string;
  agent: string;
  action_type: string;
  summary: string;
  payload: Record<string, unknown>;
  status: "pending" | "approved" | "executed" | "rejected" | "failed";
  result: string;
};
export type AuditEvent = { event: string; detail: string; created_at: string };

export type Job = {
  id: string;
  company: string;
  role: string;
  url: string;
  description: string;
  status: "saved" | "applied" | "interview" | "offer" | "rejected";
  notes: string;
  match_score: number | null;
  match_notes: string;
  cover_letter: string;
};
export type Recruiter = {
  id: string;
  name: string;
  company: string;
  email: string;
  notes: string;
};

export type Task = {
  id: string;
  title: string;
  notes: string;
  kind: "task" | "reminder" | "deadline" | "interview";
  status: "open" | "done";
  due_at: string | null;
  job_id: string | null;
};

export type LearningTopic = {
  id: string;
  name: string;
  status: "learning" | "comfortable" | "mastered";
  notes: string;
};

export type Notifications = {
  pending_approvals: number;
  due_tasks: { id: string; title: string; due_at: string | null; overdue: boolean }[];
  unread_emails: { sender: string; subject: string; snippet: string }[] | null;
  email_error: string | null;
};

export type WaAutonomy = {
  mode: string;
  emergency_stop: boolean;
  paused: boolean;
  autonomy_stopped: boolean;
  available_modes: { value: string; description: string }[];
};
export type WaContact = {
  id: string;
  name: string;
  handle: string;
  trust_level: string;
  relationship: string;
  notes: string;
  autonomy_enabled: boolean;
  allowed_actions: string[];
  forbidden_actions: string[];
  paused: boolean;
  taken_over: boolean;
  effective_mode: string;
  mode_reason: string;
};
export type WaObservation = {
  contact: WaContact;
  effective_mode: string;
  mode_reason: string;
  intent: string | null;
  needs_reply: boolean | null;
  sensitive: string[];
  urgency: string | null;
  language: string | null;
  draft: string | null;
  sent: boolean;
};
export type WaOverview = {
  mode: string;
  emergency_stop: boolean;
  channel_linked: boolean;
  contacts: (WaContact & { message_count: number })[];
};

export type StylePattern = {
  id: string;
  dimension: string;
  scope: string;
  value: string;
  confidence: number;
  evidence_count: number;
  source: string;
};
export type StyleProfile = { patterns: StylePattern[]; prompt_block: string };

export type WaDraft = {
  id: string;
  contact_id: string;
  contact_name: string;
  incoming: string;
  draft: string;
  status: string;
  final: string;
  rationale: string;
  created_at: string;
};

/** Everything the Autonomous Activity page shows, from one call. */
export type WaActivity = {
  mode: string;
  mode_description: string;
  emergency_stop: boolean;
  paused: boolean;
  autonomy_stopped: boolean;
  messages: {
    received: number;
    processed: number;
    pending: number;
    failed: number;
    backlog_seconds: number;
  };
  autonomous: {
    sent: number;
    queued: number;
    blocked: number;
    awaiting_approval: number;
    approved_by_user: number;
    corrected_by_user: number;
    unreviewed: number;
  };
  risk_breakdown: Record<string, number>;
  models_used: Record<string, number>;
  estimated_autonomous_cost_usd: number;
  autonomous_contacts: {
    id: string;
    name: string;
    handle: string;
    trust_level: string;
    allowed_actions: string[];
    forbidden_actions: string[];
    paused: boolean;
    taken_over: boolean;
    communication_confidence: number;
    reviewed_responses: number;
    correction_rate: number;
  }[];
  recent_learning: {
    kind: string;
    note: string;
    draft: string;
    final: string;
    created_at: string;
  }[];
  errors: {
    id: string;
    handle: string;
    body: string;
    attempts: number;
    last_error: string;
    received_at: string;
  }[];
};

export type WaAutonomousResponse = {
  id: string;
  contact_id: string;
  contact_name: string;
  incoming: string;
  response: string;
  decision: string;
  decision_reasons: string[];
  autonomy_mode: string;
  action_type: string;
  risk_level: string;
  risk_categories: string[];
  communication_confidence: number;
  model: string;
  estimated_cost_usd: number;
  send_status: string;
  send_error: string;
  user_reaction: string;
  correction: string;
  created_at: string;
};

export type WaReadiness = {
  advisory: string;
  contacts: {
    contact_id: string;
    contact_name: string;
    score: number;
    factors: Record<string, number>;
    notes: string[];
    blocking: string[];
  }[];
};

export type WaQueueStats = {
  received: number;
  pending: number;
  processing: number;
  done: number;
  dead: number;
  backlog_seconds: number;
};

/** Something ARIA noticed on her own, without being asked. */
export type Insight = {
  id: string;
  key: string;
  severity: "urgent" | "attention" | "fyi";
  title: string;
  detail: string;
  link: string;
  action: string;
  status: string;
  created_at: string;
};

export const api = {
  listInsights: () => request<Insight[]>("/proactive"),
  dismissInsight: (id: string) =>
    request<Insight>(`/proactive/${id}/dismiss`, { method: "POST" }),
  runProactiveChecks: () =>
    request<{ new_insights: number; keys: string[] }>("/proactive/run", {
      method: "POST",
    }),

  listDrafts: () => request<WaDraft[]>("/whatsapp/drafts"),
  decideDraft: (id: string, decision: string, final = "") =>
    request<{ status: string; lessons: string[]; sent: boolean }>(
      `/whatsapp/drafts/${id}/decide`,
      { method: "POST", body: JSON.stringify({ decision, final }) },
    ),

  getStyleProfile: () => request<StyleProfile>("/style"),
  refreshStyle: () =>
    request<{ dimensions: Record<string, string>; sample_size: number }>(
      "/style/refresh",
      { method: "POST" },
    ),
  addStyleRule: (rule: string) =>
    request<StylePattern>("/style/rules", {
      method: "POST",
      body: JSON.stringify({ rule }),
    }),
  forgetStylePattern: (id: string) =>
    request<void>(`/style/patterns/${id}`, { method: "DELETE" }),
  previewLessons: (draft: string, final: string) =>
    request<{ recorded: boolean; lessons: string[] }>("/style/preview-lessons", {
      method: "POST",
      body: JSON.stringify({ draft, final }),
    }),
  recordStyleFeedback: (kind: string, draft: string, final: string) =>
    request<{ recorded: boolean; lessons: string[] }>("/style/feedback", {
      method: "POST",
      body: JSON.stringify({ kind, draft, final }),
    }),

  waOverview: () => request<WaOverview>("/whatsapp/overview"),
  waAutonomy: () => request<WaAutonomy>("/whatsapp/autonomy"),
  waSetAutonomy: (patch: { mode?: string; emergency_stop?: boolean }) =>
    request<WaAutonomy>("/whatsapp/autonomy", {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  waEmergencyStop: () =>
    request<WaAutonomy>("/whatsapp/emergency-stop", { method: "POST" }),
  waSetTrust: (contactId: string, trust_level: string) =>
    request<WaContact>(`/whatsapp/contacts/${contactId}`, {
      method: "PATCH",
      body: JSON.stringify({ trust_level }),
    }),
  waSimulate: (handle: string, name: string, body: string) =>
    request<WaObservation>("/whatsapp/simulate", {
      method: "POST",
      body: JSON.stringify({ handle, name, body }),
    }),

  // --- autonomy: monitoring, control, and per-contact policy ---
  waActivity: () => request<WaActivity>("/whatsapp/activity"),
  waAutonomousResponses: () =>
    request<WaAutonomousResponse[]>("/whatsapp/autonomous"),
  waReactToResponse: (id: string, reaction: string, correction = "", note = "") =>
    request<{ reaction: string; lessons: string[] }>(
      `/whatsapp/autonomous/${id}/react`,
      { method: "POST", body: JSON.stringify({ reaction, correction, note }) },
    ),
  waReadiness: () => request<WaReadiness>("/whatsapp/readiness"),
  waQueue: () => request<WaQueueStats>("/whatsapp/queue"),
  waRetryQueued: (id: string) =>
    request<unknown>(`/whatsapp/queue/${id}/retry`, { method: "POST" }),

  waPause: (resume = false) =>
    request<WaAutonomy>(`/whatsapp/pause?resume=${resume}`, { method: "POST" }),
  waStopAutonomy: (resume = false) =>
    request<WaAutonomy>(`/whatsapp/stop-autonomy?resume=${resume}`, {
      method: "POST",
    }),
  waTakeOver: (contactId: string, release = false) =>
    request<WaContact>(
      `/whatsapp/contacts/${contactId}/take-over?release=${release}`,
      { method: "POST" },
    ),
  waPauseContact: (contactId: string, resume = false) =>
    request<WaContact>(
      `/whatsapp/contacts/${contactId}/pause?resume=${resume}`,
      { method: "POST" },
    ),
  /** Per-contact autonomy policy: the "John may handle greetings" editor. */
  waSetContactPolicy: (
    contactId: string,
    policy: {
      autonomy_enabled?: boolean;
      allowed_actions?: string[];
      forbidden_actions?: string[];
      trust_level?: string;
    },
  ) =>
    request<WaContact>(`/whatsapp/contacts/${contactId}`, {
      method: "PATCH",
      body: JSON.stringify(policy),
    }),
  waEvaluate: (handle: string, body: string, proposed_reply = "") =>
    request<{
      decision: string;
      reasons: string[];
      action_type: string;
      risk_level: string;
      risk_categories: string[];
      risk_reasons: string[];
      injection_suspected: boolean;
      effective_mode: string;
      communication_confidence: number;
      correction_rate: number;
    }>("/whatsapp/evaluate", {
      method: "POST",
      body: JSON.stringify({ handle, body, proposed_reply }),
    }),

  getNotifications: () => request<Notifications>("/notifications"),
  readInbox: () =>
    request<{ sender: string; subject: string; date: string; snippet: string }[]>(
      "/communication/inbox",
    ),

  listTopics: () => request<LearningTopic[]>("/learning/topics"),
  addTopic: (name: string) =>
    request<LearningTopic>("/learning/topics", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  updateTopic: (id: string, status: LearningTopic["status"]) =>
    request<LearningTopic>(`/learning/topics/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    }),
  deleteTopic: (id: string) =>
    request<void>(`/learning/topics/${id}`, { method: "DELETE" }),
  explain: (concept: string, context: string) =>
    request<{ text: string }>("/learning/explain", {
      method: "POST",
      body: JSON.stringify({ concept, context }),
    }),
  reviewCode: (code: string, question: string) =>
    request<{ text: string }>("/learning/review", {
      method: "POST",
      body: JSON.stringify({ code, question }),
    }),
  learningPath: (goal: string) =>
    request<{ text: string }>("/learning/path", {
      method: "POST",
      body: JSON.stringify({ goal }),
    }),

  listTasks: (status?: string) =>
    request<Task[]>(`/tasks${status ? `?status=${status}` : ""}`),
  addTask: (t: { title: string; kind: string; due_at: string | null; notes?: string }) =>
    request<Task>("/tasks", { method: "POST", body: JSON.stringify(t) }),
  updateTask: (id: string, patch: Partial<Pick<Task, "status" | "title" | "notes">>) =>
    request<Task>(`/tasks/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  deleteTask: (id: string) => request<void>(`/tasks/${id}`, { method: "DELETE" }),

  listJobs: () => request<Job[]>("/jobs"),
  addJob: (j: Pick<Job, "company" | "role" | "url" | "description">) =>
    request<Job>("/jobs", { method: "POST", body: JSON.stringify(j) }),
  updateJob: (id: string, patch: Partial<Pick<Job, "status" | "notes" | "description">>) =>
    request<Job>(`/jobs/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  deleteJob: (id: string) => request<void>(`/jobs/${id}`, { method: "DELETE" }),
  analyzeJob: (id: string) => request<Job>(`/jobs/${id}/analyze`, { method: "POST" }),
  draftCoverLetter: (id: string, extra = "") =>
    request<Job>(`/jobs/${id}/cover-letter`, {
      method: "POST",
      body: JSON.stringify({ extra }),
    }),
  interviewPrep: (id: string) =>
    request<{ text: string }>(`/jobs/${id}/interview-prep`, { method: "POST" }),
  listRecruiters: () => request<Recruiter[]>("/recruiters"),
  addRecruiter: (r: { name: string; company: string; email: string | null; notes: string }) =>
    request<Recruiter>("/recruiters", { method: "POST", body: JSON.stringify(r) }),
  deleteRecruiter: (id: string) =>
    request<void>(`/recruiters/${id}`, { method: "DELETE" }),

  authStatus: () => request<{ auth_enabled: boolean }>("/auth/status"),
  login: (password: string) =>
    request<{ token: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ password }),
    }),

  draftReply: (platform: string, conversation: string, instructions: string) =>
    request<{ text: string }>("/communication/draft", {
      method: "POST",
      body: JSON.stringify({ platform, conversation, instructions }),
    }),
  summarize: (conversation: string) =>
    request<{ text: string }>("/communication/summarize", {
      method: "POST",
      body: JSON.stringify({ conversation }),
    }),
  requestEmailSend: (to: string, subject: string, body: string) =>
    request<ActionRequest>("/communication/email-request", {
      method: "POST",
      body: JSON.stringify({ to, subject, body }),
    }),

  listActions: (status?: string) =>
    request<ActionRequest[]>(`/actions${status ? `?status=${status}` : ""}`),
  approveAction: (id: string) =>
    request<ActionRequest>(`/actions/${id}/approve`, { method: "POST" }),
  rejectAction: (id: string, reason: string) =>
    request<ActionRequest>(`/actions/${id}/reject`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),
  getAudit: (id: string) => request<AuditEvent[]>(`/actions/${id}/audit`),
  createDemoAction: (message: string) =>
    request<ActionRequest>("/actions/demo", {
      method: "POST",
      body: JSON.stringify({ message }),
    }),

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
