/**
 * ARIA WhatsApp bridge — READ ONLY.
 *
 * Connects to WhatsApp as a linked device, forwards every inbound message to
 * ARIA, and stops there.
 *
 * ─── The safety property ─────────────────────────────────────────────────
 * This file contains no code that sends anything to WhatsApp. Not a disabled
 * branch, not a guarded call — the capability is simply never written. The
 * socket object exposes `sendMessage`, and this process never calls it.
 *
 * That is checked mechanically: `npm run verify-readonly` fails the build if
 * any sending API appears in this directory. Safety you can grep for beats
 * safety you have to trust.
 *
 * Also deliberately off:
 *   • read receipts   — senders never see "read" because ARIA looked
 *   • presence        — ARIA never appears "online" or "typing" as you
 *   • history sync    — only messages arriving from now on
 */

// Package note: the library moved from "@whiskeysockets/baileys" to plain
// "baileys". Pinned to an exact prerelease because 7.x has no stable release
// yet — this is the same version OpenClaw ships, so it is known to work.
// Exports are named; the default export is makeWASocket itself.
import makeWASocket, {
  DisconnectReason,
  fetchLatestBaileysVersion,
  useMultiFileAuthState,
} from "baileys";
import pino from "pino";
import qrcode from "qrcode-terminal";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const AUTH_DIR = join(HERE, "auth");
const POST_TIMEOUT_MS = 20000;

// ── config ────────────────────────────────────────────────────────────────
function loadConfig() {
  let file = {};
  try {
    file = JSON.parse(readFileSync(join(HERE, "config.json"), "utf8"));
  } catch {
    /* env vars may supply everything */
  }
  const url =
    process.env.ARIA_INGEST_URL || file.url || "http://127.0.0.1:8000/whatsapp/ingest";
  const secret = process.env.ARIA_INGEST_SECRET || file.secret || "";
  if (!secret) {
    console.error(
      "[bridge] No ingest secret. Copy config.example.json to config.json and set\n" +
        '         "secret" to OPENCLAW_INGEST_SECRET from ARIA\'s .env.',
    );
    process.exit(1);
  }
  return { url, secret };
}

const cfg = loadConfig();
const log = pino({ level: "warn" }); // Baileys is extremely chatty at info

// ── message extraction ────────────────────────────────────────────────────

/** Pull readable text out of the many shapes a WhatsApp message can take. */
function extractText(message) {
  if (!message) return "";
  return (
    message.conversation ||
    message.extendedTextMessage?.text ||
    message.imageMessage?.caption ||
    message.videoMessage?.caption ||
    message.documentMessage?.caption ||
    ""
  ).trim();
}

/** Forward one message to ARIA. Never throws — ARIA being down must not kill
 *  the bridge, and a failure must be visible rather than silent. */
async function forwardToAria({ handle, name, body, direction }) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), POST_TIMEOUT_MS);
  try {
    const res = await fetch(cfg.url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-ARIA-Ingest-Secret": cfg.secret,
      },
      body: JSON.stringify({ handle, name, body, direction }),
      signal: controller.signal,
    });
    if (res.ok) {
      const data = await res.json().catch(() => ({}));
      console.log(
        `[bridge] → ARIA  ${direction}  ${name || handle}: ` +
          `"${body.slice(0, 50)}${body.length > 50 ? "…" : ""}"` +
          (data.effective_mode ? `  [${data.effective_mode}]` : ""),
      );
    } else {
      console.warn(`[bridge] ARIA returned ${res.status} — message not stored`);
    }
  } catch (err) {
    console.warn(`[bridge] forward failed: ${err?.message || err}`);
  } finally {
    clearTimeout(timer);
  }
}

// ── connection ────────────────────────────────────────────────────────────

async function start() {
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  const { version } = await fetchLatestBaileysVersion();

  const sock = makeWASocket({
    version,
    auth: state,
    logger: log,
    printQRInTerminal: false, // we render it ourselves, larger
    // Never announce presence: ARIA must not make you look online or typing.
    markOnlineOnConnect: false,
    // Don't pull the full archive — ARIA learns from messages arriving now.
    // NOTE: we deliberately do NOT set shouldSyncHistoryMessage:()=>false.
    // Baileys warns that blocking all sync starves it of LID mappings and
    // causes session instability. `syncFullHistory: false` is the supported
    // way to stay light; history messages are filtered at the handler
    // instead (we only act on type === "notify").
    syncFullHistory: false,
  });

  sock.ev.on("creds.update", saveCreds);

  sock.ev.on("connection.update", (update) => {
    const { connection, lastDisconnect, qr } = update;

    if (qr) {
      console.log("\n  Scan this with WhatsApp on your phone:");
      console.log("  (WhatsApp → Settings → Linked Devices → Link a Device)\n");
      qrcode.generate(qr, { small: true });
    }

    if (connection === "open") {
      const me = sock.user?.id?.split(":")[0] || "unknown";
      console.log(`\n  ✓ Connected as +${me} — READ ONLY.`);
      console.log("  ARIA will observe messages. It cannot reply.\n");
    }

    if (connection === "close") {
      // Baileys attaches a Boom error; read the status without pulling in
      // @hapi/boom as a direct dependency.
      const status = lastDisconnect?.error?.output?.statusCode;
      const loggedOut = status === DisconnectReason.loggedOut;
      if (loggedOut) {
        console.error(
          "\n  Logged out on the phone. Delete the ./auth folder and re-pair.\n",
        );
        process.exit(1);
      }
      console.warn(`  connection closed (${status}) — reconnecting…`);
      setTimeout(start, 3000);
    }
  });

  sock.ev.on("messages.upsert", async ({ messages, type }) => {
    // "notify" = messages arriving now. "append" is history backfill, which
    // we skip: ARIA learns from the present, not by hoovering your archive.
    if (type !== "notify") return;

    for (const msg of messages) {
      const jid = msg.key?.remoteJid || "";
      if (jid === "status@broadcast") continue; // status updates, not conversation
      if (jid.endsWith("@g.us")) continue; // groups: out of scope for now

      const body = extractText(msg.message);
      if (!body) continue; // media-only, reactions, receipts, etc.

      // fromMe = MORICE's own outgoing message. Worth forwarding: it is how
      // ARIA learns his writing style. Marked "out" so it is never treated
      // as something to reply to.
      const direction = msg.key?.fromMe ? "out" : "in";

      await forwardToAria({
        handle: jid,
        name: msg.pushName || "",
        body,
        direction,
      });
    }
  });
}

console.log("\n  ARIA WhatsApp bridge (read-only)");
console.log(`  forwarding to ${cfg.url}\n`);
start().catch((err) => {
  console.error("[bridge] fatal:", err);
  process.exit(1);
});
