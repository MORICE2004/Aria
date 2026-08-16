/**
 * ARIA bridge — forwards inbound messages to ARIA for observation.
 *
 * Runs inside the OpenClaw gateway on `message:received`. It is deliberately
 * one-directional: OpenClaw ignores `event.messages` for message:* events, so
 * this hook has no way to reply even if it tried.
 */

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const POST_TIMEOUT_MS = 15000;

/** Load config from config.json, with env-var overrides. */
function loadConfig() {
  let fileCfg = {};
  try {
    fileCfg = JSON.parse(readFileSync(join(HERE, "config.json"), "utf8"));
  } catch {
    // Missing/unreadable config is fine if env vars supply the values.
  }
  return {
    url:
      process.env.ARIA_INGEST_URL ||
      fileCfg.url ||
      "http://127.0.0.1:8000/whatsapp/ingest",
    secret: process.env.ARIA_INGEST_SECRET || fileCfg.secret || "",
    channels: fileCfg.channels || ["whatsapp"],
  };
}

/** Best-effort display name for the sender. */
function senderName(context) {
  const meta = context?.metadata || {};
  return meta.senderName || meta.pushName || meta.name || "";
}

/** Stable handle for the sender: prefer the provider id, fall back to `from`. */
function senderHandle(context) {
  const meta = context?.metadata || {};
  return String(meta.senderId || context?.from || "").trim();
}

const handler = async (event) => {
  if (event?.type !== "message" || event?.action !== "received") return;

  const cfg = loadConfig();
  const context = event.context || {};
  const channel = String(context.channelId || "");

  // Forward everything by default. An earlier version filtered on
  // channelId containing "whatsapp" and silently dropped every message,
  // because the WhatsApp Web provider does not label itself that way.
  // Filtering is now opt-in via config.channels, and a skip is logged so a
  // dropped message is never invisible.
  if (Array.isArray(cfg.channels) && cfg.channels.length > 0) {
    const match = cfg.channels.some((c) => channel.toLowerCase().includes(String(c).toLowerCase()));
    if (!match) {
      console.warn(`[aria-bridge] skipping channelId="${channel}" (not in filter)`);
      return;
    }
  }
  console.log(`[aria-bridge] forwarding message from channelId="${channel}"`);

  if (!cfg.secret) {
    console.warn("[aria-bridge] no secret configured — not forwarding");
    return;
  }

  const handle = senderHandle(context);
  const body = String(context.content || "").trim();
  if (!handle || !body) return; // nothing useful to observe

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), POST_TIMEOUT_MS);
  try {
    const res = await fetch(cfg.url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-ARIA-Ingest-Secret": cfg.secret,
      },
      body: JSON.stringify({
        handle,
        name: senderName(context),
        body,
        direction: "in",
      }),
      signal: controller.signal,
    });
    if (!res.ok) {
      // Loud, but non-fatal: ARIA being unhappy must not break messaging.
      console.warn(`[aria-bridge] ARIA returned ${res.status}`);
    }
  } catch (err) {
    console.warn(`[aria-bridge] forward failed: ${err?.message || err}`);
  } finally {
    clearTimeout(timer);
  }
};

export default handler;
