/**
 * ARIA WhatsApp sender — the ONLY process that can send a message.
 *
 * ─── Why this is a separate process ──────────────────────────────────────
 * The observer (index.js) receives messages and cannot send: not a disabled
 * branch, the capability is simply not written, and `npm run verify-readonly`
 * fails the build if it ever appears. That guarantee is worth keeping, so
 * sending lives here instead of being added there.
 *
 * The separation is real, not cosmetic:
 *
 *   • This process links as its OWN WhatsApp device, with its own auth
 *     directory. MORICE can unlink it from his phone at any time and ARIA
 *     physically cannot send, regardless of what any software says. That is a
 *     kill switch below the level of ARIA's own code, and it is the one that
 *     still works if ARIA's code is wrong.
 *
 *   • This process contains no reasoning. It cannot decide to send anything.
 *     It asks ARIA for approved messages and delivers exactly those. Every
 *     judgement — risk, contact policy, autonomy mode, kill switch — was made
 *     before the message reached the queue, and ARIA re-checks the stop
 *     controls at handover.
 *
 * So: the process that thinks has no socket, and the process with the socket
 * cannot think. Neither can send a message alone.
 *
 * Start it only when autonomous or approved sending is genuinely wanted:
 *   node sender.js
 * Not started by start-whatsapp-bridge.ps1 — observing is the default, and
 * sending should require a deliberate act.
 */

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
// Deliberately NOT the observer's auth directory: a separate linked device.
const AUTH_DIR = join(HERE, "auth-sender");
const POLL_MS = 3000;
const HTTP_TIMEOUT_MS = 15000;

function loadConfig() {
  let file = {};
  try {
    file = JSON.parse(readFileSync(join(HERE, "config.json"), "utf8"));
  } catch {
    /* env vars may supply everything */
  }
  const base =
    process.env.ARIA_API_URL ||
    (file.url || "http://127.0.0.1:8000/whatsapp/ingest").replace(/\/ingest$/, "");
  const secret = process.env.ARIA_INGEST_SECRET || file.secret || "";
  if (!secret) {
    console.error("[sender] No shared secret. Set it in config.json.");
    process.exit(1);
  }
  return { claimUrl: `${base}/outbound/claim`, confirmUrl: `${base}/outbound/confirm`, secret };
}

const cfg = loadConfig();
const log = pino({ level: "warn" });

async function post(url, body) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), HTTP_TIMEOUT_MS);
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-ARIA-Ingest-Secret": cfg.secret,
      },
      body: JSON.stringify(body ?? {}),
      signal: controller.signal,
    });
    if (!res.ok) return null;
    return await res.json().catch(() => null);
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Ask ARIA for approved messages and deliver them.
 *
 * Claiming is what re-checks the stop controls: if MORICE has pressed stop
 * since a message was approved, ARIA cancels it here and hands back nothing.
 * That is why this polls rather than being pushed to — the last decision about
 * whether a message goes out belongs to ARIA, at the latest possible moment.
 */
async function deliverApproved(sock) {
  const claimed = await post(cfg.claimUrl);
  if (!claimed?.messages?.length) return;

  for (const message of claimed.messages) {
    try {
      await sock.sendMessage(message.handle, { text: message.body });
      await post(cfg.confirmUrl, { id: message.id, ok: true });
      console.log(
        `[sender] sent to ${message.handle}: ` +
          `"${message.body.slice(0, 60)}${message.body.length > 60 ? "..." : ""}"`,
      );
    } catch (err) {
      const error = err?.message || String(err);
      // Report the failure rather than retrying blindly: ARIA owns the
      // decision about whether a failed message should be tried again.
      await post(cfg.confirmUrl, { id: message.id, ok: false, error });
      console.error(`[sender] FAILED to ${message.handle}: ${error}`);
    }
  }
}

async function start() {
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  const { version } = await fetchLatestBaileysVersion();

  const sock = makeWASocket({
    version,
    auth: state,
    logger: log,
    printQRInTerminal: false,
    markOnlineOnConnect: false,
    syncFullHistory: false,
  });

  sock.ev.on("creds.update", saveCreds);

  sock.ev.on("connection.update", (update) => {
    const { connection, lastDisconnect, qr } = update;

    if (qr) {
      console.log("\n  Link ARIA's SENDER as a second device:");
      console.log("  (WhatsApp -> Settings -> Linked Devices -> Link a Device)");
      console.log("  Unlink this device at any time to hard-stop all sending.\n");
      qrcode.generate(qr, { small: true });
    }

    if (connection === "open") {
      const me = sock.user?.id?.split(":")[0] || "unknown";
      console.log(`\n  Connected as +${me} - SENDER.`);
      console.log("  Delivers only messages ARIA has already approved.\n");
      poll(sock);
    }

    if (connection === "close") {
      const status = lastDisconnect?.error?.output?.statusCode;
      if (status === DisconnectReason.loggedOut) {
        console.error("\n  Sender unlinked on the phone. Sending is now off.\n");
        process.exit(1);
      }
      console.warn(`  connection closed (${status}) - reconnecting...`);
      setTimeout(start, 3000);
    }
  });
}

let polling = false;
function poll(sock) {
  if (polling) return;
  polling = true;
  const tick = async () => {
    try {
      await deliverApproved(sock);
    } catch (err) {
      console.error(`[sender] poll failed: ${err?.message || err}`);
    }
    setTimeout(tick, POLL_MS).unref?.();
  };
  tick();
}

console.log("\n  ARIA WhatsApp sender");
console.log(`  polling ${cfg.claimUrl}`);
console.log("  This process can send. The observer still cannot.\n");
start().catch((err) => {
  console.error("[sender] fatal:", err);
  process.exit(1);
});
