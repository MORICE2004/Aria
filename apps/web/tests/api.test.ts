/**
 * Tests for the API client.
 *
 * This file is worth testing before any page is, because every page depends on
 * it and its failures are invisible: a call that forgets the auth header does
 * not look broken in code review, it looks broken to MORICE as "API error 401"
 * on the one screen he uses most.
 *
 * That is not hypothetical. `sendMessage` is the only call that cannot go
 * through `request()` — it needs the raw body to stream — and it shipped
 * without the header, which meant chat was the single unauthenticated call in
 * the client from the moment a password was set.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api, API_URL } from "@/lib/api";

/** jsdom refuses real navigation, so location is replaced with a plain object. */
function stubLocation() {
  const location = { href: "", hostname: "localhost" };
  Object.defineProperty(window, "location", {
    configurable: true,
    writable: true,
    value: location,
  });
  return location;
}

/** A fetch that returns one canned JSON response and records what it was sent. */
function mockJson(body: unknown, status = 200) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/** A fetch whose body streams the given chunks, like the chat endpoint does. */
function mockStream(chunks: string[], status = 200) {
  const encoder = new TextEncoder();
  let index = 0;
  const fetchMock = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    body: {
      getReader: () => ({
        read: async () =>
          index < chunks.length
            ? { done: false, value: encoder.encode(chunks[index++]) }
            : { done: true, value: undefined },
      }),
    },
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function headersOf(fetchMock: ReturnType<typeof vi.fn>): Record<string, string> {
  return fetchMock.mock.calls[0][1].headers as Record<string, string>;
}

describe("authentication", () => {
  beforeEach(stubLocation);

  it("attaches the stored token to a request", async () => {
    localStorage.setItem("aria_token", "token-123");
    const fetchMock = mockJson([]);

    await api.listMemories();

    expect(headersOf(fetchMock).Authorization).toBe("Bearer token-123");
  });

  it("sends no Authorization header when nobody is logged in", async () => {
    const fetchMock = mockJson([]);

    await api.listMemories();

    expect(headersOf(fetchMock).Authorization).toBeUndefined();
  });

  it("attaches the token when sending a chat message", async () => {
    // The regression this file exists for. sendMessage builds its own fetch,
    // so it does not inherit the header from `request()`.
    localStorage.setItem("aria_token", "token-123");
    const fetchMock = mockStream(["hello"]);

    await api.sendMessage("conversation-1", "hi", () => {});

    expect(headersOf(fetchMock).Authorization).toBe("Bearer token-123");
  });

  it("attaches the token when uploading a document", async () => {
    localStorage.setItem("aria_token", "token-123");
    const fetchMock = mockJson({ id: "d1" }, 201);

    await api.uploadDocument(new File(["cv"], "cv.txt", { type: "text/plain" }));

    expect(headersOf(fetchMock).Authorization).toBe("Bearer token-123");
  });
});

describe("an expired session", () => {
  it("sends him to the login page rather than showing an error code", async () => {
    const location = stubLocation();
    mockJson({ detail: "Not authenticated" }, 401);

    await expect(api.listMemories()).rejects.toThrow();

    expect(location.href).toBe("/login");
  });

  it("sends him to the login page from chat too", async () => {
    const location = stubLocation();
    mockStream([], 401);

    await expect(
      api.sendMessage("conversation-1", "hi", () => {}),
    ).rejects.toThrow();

    expect(location.href).toBe("/login");
  });
});

describe("errors", () => {
  beforeEach(stubLocation);

  it("surfaces the API's own explanation", async () => {
    // "SMTP is not configured" is actionable. "API error 400" is not.
    mockJson({ detail: "SMTP is not configured" }, 400);

    await expect(api.listJobs()).rejects.toThrow("SMTP is not configured");
  });

  it("falls back to the status and path when there is no explanation", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => {
        throw new Error("no body");
      },
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.listJobs()).rejects.toThrow("API error 500 on /jobs");
  });
});

describe("responses", () => {
  beforeEach(stubLocation);

  it("does not try to parse a body out of 204 No Content", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
      json: async () => {
        throw new Error("204 has no body");
      },
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.deleteMemory("m1")).resolves.toBeUndefined();
  });

  it("streams chat chunks to the caller in order", async () => {
    mockStream(["Remembered", ": ", "the passport"]);
    const received: string[] = [];

    await api.sendMessage("conversation-1", "remember that", (c) =>
      received.push(c),
    );

    expect(received.join("")).toBe("Remembered: the passport");
  });

  it("talks to the API on the host that served the page", () => {
    // So the dashboard opened from a phone at 192.168.x.x:3000 reaches the API
    // on the same machine without being reconfigured.
    expect(API_URL).toBe("http://localhost:8000");
  });
});

describe("request shapes", () => {
  beforeEach(stubLocation);

  it("escapes a memory search query into the URL", async () => {
    const fetchMock = mockJson([]);

    await api.searchMemories("rent & deposit");

    expect(fetchMock.mock.calls[0][0]).toBe(
      "http://localhost:8000/memory/search?q=rent%20%26%20deposit",
    );
  });

  it("leaves Content-Type to the browser when uploading a file", async () => {
    // A multipart upload needs the boundary the browser generates; setting the
    // header by hand makes the body unparseable on the server.
    const fetchMock = mockJson({ id: "d1" }, 201);

    await api.uploadDocument(new File(["cv"], "cv.txt", { type: "text/plain" }));

    expect(headersOf(fetchMock)["Content-Type"]).toBeUndefined();
  });
});
