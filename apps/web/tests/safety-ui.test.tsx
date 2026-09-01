/**
 * Tests for the parts of the interface that carry a safety promise.
 *
 * ARIA's guarantees are enforced in the backend, but MORICE only ever sees the
 * frontend. A component that renders a queued message as sent, or that quietly
 * stops warning him that ARIA has no password, breaks the promise as
 * effectively as a backend bug would — and is far easier to break by accident,
 * because nothing fails when the wording drifts.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DraftReview } from "@/components/draft-review";
import { SecurityBanner } from "@/components/security-banner";
import type { WaDraft } from "@/lib/api";

function draft(overrides: Partial<WaDraft> = {}): WaDraft {
  return {
    id: "draft-1",
    contact_id: "contact-1",
    contact_name: "Ann",
    incoming: "are we still on for Friday?",
    draft: "Yes, Friday works.",
    status: "pending",
    final: "",
    rationale: "Routine reply, low risk.",
    created_at: "2026-09-01T06:00:00Z",
    ...overrides,
  };
}

describe("the security banner", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("warns loudly when ARIA has no password", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          auth_enabled: false,
          warning: "Auth is disabled. Anyone who can reach this API controls ARIA.",
        }),
      }),
    );

    render(<SecurityBanner />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Anyone who can reach this API controls ARIA");
    // And says what it means in practice, not just that something is wrong.
    expect(alert).toHaveTextContent("refuses to send any on her own");
  });

  it("says nothing when a password is set", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ auth_enabled: true, warning: "" }),
      }),
    );

    render(<SecurityBanner />);

    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });

  it("stays quiet when the API is unreachable", async () => {
    // A network failure is a different problem, and claiming ARIA is
    // unprotected because the check failed would teach him to ignore it.
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));

    render(<SecurityBanner />);

    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });
});

describe("draft review", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("never offers to send, because ARIA cannot", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => [draft()] }),
    );

    render(<DraftReview />);
    await screen.findByText("Ann wrote:");

    expect(screen.queryByRole("button", { name: /^send$/i })).toBeNull();
    expect(screen.getByRole("button", { name: "Copy" })).toBeInTheDocument();
    expect(
      screen.getByText(/ARIA cannot send\. Copy the reply and send it yourself/),
    ).toBeInTheDocument();
  });

  it("offers approval until he edits, then offers to learn from the edit", async () => {
    // The correction is the valuable outcome, so it must not be reachable only
    // through a menu: editing the text changes the primary button itself.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => [draft()] }),
    );

    render(<DraftReview />);
    const box = await screen.findByLabelText("Suggested reply to Ann");

    expect(screen.getByRole("button", { name: "Good as-is" })).toBeInTheDocument();

    await userEvent.type(box, " See you then.");

    expect(screen.queryByRole("button", { name: "Good as-is" })).toBeNull();
    expect(
      screen.getByRole("button", { name: /Save my version & teach ARIA/ }),
    ).toBeInTheDocument();
  });

  it("explains an empty queue rather than showing a blank panel", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => [] }),
    );

    render(<DraftReview />);

    expect(await screen.findByText(/Nothing waiting/)).toBeInTheDocument();
  });

  it("shows the reason a draft was written, not just the draft", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => [draft({ rationale: "Routine reply, low risk." })],
      }),
    );

    render(<DraftReview />);

    expect(await screen.findByText("Routine reply, low risk.")).toBeInTheDocument();
  });
});
