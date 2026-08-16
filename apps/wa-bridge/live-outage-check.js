/**
 * Live message-loss check against a REAL running ARIA.
 *
 * Unit tests prove the spool holds messages when a fake deliver function
 * returns false. This proves it against an API process that is genuinely
 * killed and genuinely restarted — the failure the original code lost
 * messages to.
 *
 * It does NOT touch WhatsApp. Messages are injected into the same spool the
 * bridge writes to, and travel the same delivery code path.
 *
 * Usage:
 *   node live-outage-check.js phase1   # with ARIA UP: baseline delivery
 *   node live-outage-check.js phase2   # with ARIA DOWN: messages must hold
 *   node live-outage-check.js phase3   # with ARIA UP again: must all arrive
 *
 * Split into phases because stopping and starting the API is the operator's
 * job, not this script's — a test that can kill your services is a footgun.
 */

import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { makeDeliver } from "./deliver.js";
import { Spool } from "./spool.js";

const HERE = dirname(fileURLToPath(import.meta.url));
// A dedicated directory so a check never disturbs real spooled traffic, and
// a fixed name so phase 2 and phase 3 share state across process runs.
const SPOOL_DIR = join(tmpdir(), "aria-outage-check-spool");

function config() {
  const file = JSON.parse(readFileSync(join(HERE, "config.json"), "utf8"));
  return {
    url: process.env.ARIA_INGEST_URL || file.url,
    secret: process.env.ARIA_INGEST_SECRET || file.secret,
  };
}

const HANDLE = "outage-check@s.whatsapp.net";
const messages = [
  { key: "outage.1", body: "message sent while ARIA was alive" },
  { key: "outage.2", body: "message sent during the outage" },
  { key: "outage.3", body: "second message during the outage" },
  { key: "outage.4", body: "third message during the outage" },
];

const phase = process.argv[2];
const spool = new Spool(SPOOL_DIR);
const deliver = makeDeliver(config());

function enqueue({ key, body }) {
  spool.enqueue({
    dedupeKey: key,
    handle: HANDLE,
    name: "Outage Check",
    body,
    direction: "in",
    timestamp: Math.floor(Date.now() / 1000),
    receivedAt: Date.now(),
  });
}

function report(label) {
  const c = spool.counts();
  console.log(`  ${label}: pending=${c.pending} dead=${c.dead}`);
  return c;
}

if (phase === "phase1") {
  console.log("\nPHASE 1 — ARIA is UP. Baseline: a message delivers normally.");
  enqueue(messages[0]);
  report("after enqueue");
  const result = await spool.drain(deliver);
  const counts = report("after drain");
  if (result.delivered !== 1 || counts.pending !== 0) {
    console.error("\nFAIL: baseline delivery did not work. Is ARIA running?");
    process.exit(1);
  }
  console.log("\nPASS: baseline delivery works.");
  console.log("Now STOP the ARIA API, then run: node live-outage-check.js phase2\n");
} else if (phase === "phase2") {
  console.log("\nPHASE 2 — ARIA must be DOWN. Messages must be held, not lost.");
  for (const m of messages.slice(1)) enqueue(m);
  report("after enqueue");

  const result = await spool.drain(deliver);
  const counts = report("after drain against a dead API");

  if (result.delivered > 0) {
    console.error("\nFAIL: something was delivered. ARIA is still running.");
    process.exit(1);
  }
  if (counts.pending !== 3) {
    console.error(`\nFAIL: expected 3 held messages, found ${counts.pending}.`);
    console.error("MESSAGES WERE LOST. This is the bug the spool exists to fix.");
    process.exit(1);
  }
  console.log("\nPASS: 3 messages held on disk while ARIA was unreachable.");
  console.log(`Spool directory: ${join(SPOOL_DIR, "pending")}`);
  console.log("Now START the ARIA API, then run: node live-outage-check.js phase3\n");
} else if (phase === "phase3") {
  console.log("\nPHASE 3 — ARIA is UP again. Held messages must all arrive.");
  report("before drain");

  const result = await spool.drain(deliver);
  const counts = report("after drain");

  if (counts.pending !== 0) {
    console.error(`\nFAIL: ${counts.pending} message(s) still undelivered.`);
    process.exit(1);
  }
  console.log(`\nPASS: ${result.delivered} held message(s) delivered after recovery.`);
  console.log("Verify at: GET /whatsapp/queue and /whatsapp/queue/items\n");
} else {
  console.error("Usage: node live-outage-check.js phase1|phase2|phase3");
  process.exit(2);
}
