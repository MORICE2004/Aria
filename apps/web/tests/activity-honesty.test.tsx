/**
 * The activity page must never claim ARIA sent something she only queued.
 *
 * This is the invariant the whole outbound design exists to protect: the
 * transport is read-only until MORICE links a sender device, so until he does,
 * every autonomous reply is written and held. A page that reports those as
 * "sent" tells him the safety property is not working when it is — or worse,
 * tells him a message reached someone when it did not.
 *
 * The wording is the feature here, so the wording is what is asserted.
 */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ActivityPage from "@/app/activity/page";
import type { WaActivity, WaAutonomousResponse } from "@/lib/api";

function activity(overrides: Partial<WaActivity["autonomous"]> = {}): WaActivity {
  return {
    mode: "limited_autonomy",
    mode_description: "ARIA answers routine messages from trusted contacts.",
    emergency_stop: false,
    paused: false,
    autonomy_stopped: false,
    messages: {
      received: 3,
      processed: 3,
      pending: 0,
      failed: 0,
      backlog_seconds: 0,
    },
    autonomous: {
      sent: 0,
      queued: 2,
      blocked: 0,
      awaiting_approval: 0,
      approved_by_user: 0,
      corrected_by_user: 0,
      unreviewed: 2,
      ...overrides,
    },
    risk_breakdown: { low: 2 },
    models_used: { "gemini-2.5-flash": 2 },
    estimated_autonomous_cost_usd: 0.0012,
    autonomous_contacts: [],
    recent_learning: [],
    errors: [],
  };
}

function response(
  overrides: Partial<WaAutonomousResponse> = {},
): WaAutonomousResponse {
  return {
    id: "response-1",
    contact_id: "contact-1",
    contact_name: "Friend",
    incoming: "you around later?",
    response: "Yeah, should be free after six.",
    decision: "auto_send",
    decision_reasons: ["trusted contact", "routine reply"],
    autonomy_mode: "limited_autonomy",
    action_type: "routine_reply",
    risk_level: "low",
    risk_categories: [],
    communication_confidence: 0.95,
    model: "gemini-2.5-flash",
    estimated_cost_usd: 0.0006,
    send_status: "queued",
    send_error: "",
    user_reaction: "none",
    correction: "",
    created_at: "2026-09-01T06:00:00Z",
    ...overrides,
  };
}

/** Routes each of the page's three loads to its own canned payload. */
function mockApi(a: WaActivity, responses: WaAutonomousResponse[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((url: string) => {
      const body = url.includes("/whatsapp/activity")
        ? a
        : url.includes("/whatsapp/autonomous")
          ? responses
          : { advisory: "", contacts: [] };
      return Promise.resolve({ ok: true, status: 200, json: async () => body });
    }),
  );
}

describe("a reply ARIA wrote but could not deliver", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("is counted as queued, and not as delivered", async () => {
    mockApi(activity(), [response()]);

    render(<ActivityPage />);
    await screen.findByText("Queued");

    // Both counters exist, and the queued one carries the warning.
    expect(screen.getByText("Delivered")).toBeInTheDocument();
    expect(screen.getByText("written, not delivered")).toBeInTheDocument();
  });

  it("is described as written and waiting, never as replied", async () => {
    mockApi(activity(), [response()]);

    render(<ActivityPage />);

    expect(
      await screen.findByText(/ARIA wrote, and it is still waiting to go out/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/ARIA replied:/)).toBeNull();
    expect(screen.getByText("queued - not delivered")).toBeInTheDocument();
  });

  it("says ARIA replied only once the message actually went", async () => {
    mockApi(activity({ sent: 1, queued: 0 }), [
      response({ send_status: "sent" }),
    ]);

    render(<ActivityPage />);

    expect(await screen.findByText(/ARIA replied:/)).toBeInTheDocument();
    expect(screen.queryByText(/still waiting to go out/)).toBeNull();
  });

  it("says plainly when a message never left at all", async () => {
    mockApi(activity({ blocked: 1, queued: 0 }), [
      response({ send_status: "blocked", send_error: "emergency stop" }),
    ]);

    render(<ActivityPage />);

    expect(await screen.findByText(/ARIA wrote, and it never left/)).toBeInTheDocument();
  });

  it("describes the section as what ARIA wrote, not what she sent", async () => {
    mockApi(activity(), []);

    render(<ActivityPage />);

    expect(
      await screen.findByText(/ARIA has not written anything on her own/),
    ).toBeInTheDocument();
  });
});
