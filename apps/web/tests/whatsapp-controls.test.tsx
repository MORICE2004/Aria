/**
 * The WhatsApp page is where autonomy is granted and where it is stopped, so
 * it is the page whose display bugs cost the most.
 *
 * Two failures matter more than the rest. If it describes ARIA's autonomy
 * wrongly, MORICE makes decisions about a system that is not the one in front
 * of him — and the direction of the error does not save him, because
 * understating autonomy is what stops him from turning it down. If the kill
 * switch calls the wrong endpoint, the one control that must always work is
 * the one that does not.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import WhatsAppPage from "@/app/whatsapp/page";
import type { WaAutonomy, WaOverview } from "@/lib/api";

function autonomy(overrides: Partial<WaAutonomy> = {}): WaAutonomy {
  return {
    mode: "limited_autonomy",
    emergency_stop: false,
    paused: false,
    autonomy_stopped: false,
    available_modes: [],
    ...overrides,
  };
}

function overview(overrides: Partial<WaOverview> = {}): WaOverview {
  return {
    mode: "limited_autonomy",
    emergency_stop: false,
    channel_linked: false,
    contacts: [],
    ...overrides,
  };
}

/** Records every request the page makes, so the kill switch can be traced. */
function mockApi(o: WaOverview, a: WaAutonomy) {
  const calls: { url: string; method: string }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      calls.push({ url, method: init?.method ?? "GET" });
      const body = url.includes("/whatsapp/overview")
        ? o
        : url.includes("/whatsapp/autonomy") || url.includes("/emergency-stop")
          ? a
          : [];
      return Promise.resolve({ ok: true, status: 200, json: async () => body });
    }),
  );
  return calls;
}

describe("how the page describes ARIA's autonomy", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("never claims observe mode while she is in limited autonomy", async () => {
    // The regression: the subtitle asserted observe mode unconditionally, so
    // the page reporting on autonomy was the one understating it.
    mockApi(overview(), autonomy());

    render(<WhatsAppPage />);
    await screen.findByText("limited_autonomy");

    expect(
      screen.queryByText(/ARIA is in observe mode/),
    ).toBeNull();
    expect(
      screen.queryByText(/has no ability to send/),
    ).toBeNull();
  });

  it("shows the mode the API reports", async () => {
    mockApi(overview({ mode: "observe" }), autonomy({ mode: "observe" }));

    render(<WhatsAppPage />);

    expect(await screen.findByText("observe")).toBeInTheDocument();
  });

  it("says ARIA is seeing nothing when no device is linked", async () => {
    mockApi(overview({ channel_linked: false }), autonomy());

    render(<WhatsAppPage />);

    const notice = await screen.findByText(/No WhatsApp device is linked/);
    // And points at a command that exists. It used to name the OpenClaw
    // gateway, which the Baileys bridge replaced.
    expect(notice).toHaveTextContent("start-whatsapp-bridge.ps1");
    expect(screen.queryByText(/openclaw channels login/)).toBeNull();
  });
});

describe("the kill switch", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("calls the emergency stop endpoint", async () => {
    const calls = mockApi(overview(), autonomy());

    render(<WhatsAppPage />);
    await userEvent.click(await screen.findByRole("button", { name: /Emergency stop/ }));

    expect(
      calls.some(
        (c) => c.url.includes("/whatsapp/emergency-stop") && c.method === "POST",
      ),
    ).toBe(true);
  });

  it("offers to clear the stop, and explains what is blocked while it holds", async () => {
    mockApi(
      overview({ emergency_stop: true }),
      autonomy({ emergency_stop: true, mode: "observe" }),
    );

    render(<WhatsAppPage />);

    expect(
      await screen.findByRole("button", { name: /Clear emergency stop/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/All external action is blocked and the mode is forced to observe/),
    ).toBeInTheDocument();
  });

  it("disables the mode buttons while the stop is active", async () => {
    // Otherwise the page offers a control that silently does nothing.
    mockApi(
      overview({ emergency_stop: true }),
      autonomy({ emergency_stop: true, mode: "observe" }),
    );

    render(<WhatsAppPage />);
    await screen.findByRole("button", { name: /Clear emergency stop/ });

    expect(screen.getByRole("button", { name: "suggest" })).toBeDisabled();
  });
});
