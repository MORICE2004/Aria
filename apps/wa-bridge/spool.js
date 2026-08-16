/**
 * Durable on-disk spool for inbound WhatsApp messages.
 *
 * ─── The bug this exists to kill ─────────────────────────────────────────
 * The bridge used to POST each message straight to ARIA and, if the POST
 * failed, log a warning. That was the entire error handling. If ARIA was
 * restarting — which happens on every code change — the message was gone.
 * WhatsApp had already delivered it, so nothing would ever redeliver it.
 * There was not even a record that it had existed.
 *
 * ─── The rule now ────────────────────────────────────────────────────────
 * A message is written to disk and fsynced BEFORE the network is touched,
 * and its file is deleted only after ARIA has positively acknowledged it.
 * Anything in `pending/` is, by definition, not yet safe at ARIA's end.
 *
 * Crash safety comes from write-to-temp-then-rename: rename is atomic on
 * both NTFS and POSIX, so a spool file is either absent or complete. A
 * half-written message is not a state that can exist.
 *
 * Filenames sort chronologically, so draining in directory order replays a
 * backlog in the order the messages arrived. Out-of-order replay of a
 * conversation would be worse than a delay.
 */

import {
  closeSync,
  fsyncSync,
  mkdirSync,
  openSync,
  readFileSync,
  readdirSync,
  renameSync,
  unlinkSync,
  writeFileSync,
  writeSync,
} from "node:fs";
import { join } from "node:path";

// After this many failed deliveries a message stops being retried and is
// parked in dead/ for a human. It is never deleted — a message ARIA could not
// accept is exactly the one worth keeping.
const MAX_ATTEMPTS = 20;

// Backoff between drain sweeps: 2s doubling to 60s. Fast enough that a normal
// API restart is invisible, slow enough not to hammer a service that is down.
const BACKOFF_MIN_MS = 2000;
const BACKOFF_MAX_MS = 60000;

export class Spool {
  constructor(rootDir) {
    this.pendingDir = join(rootDir, "pending");
    this.deadDir = join(rootDir, "dead");
    mkdirSync(this.pendingDir, { recursive: true });
    mkdirSync(this.deadDir, { recursive: true });
    this.backoffMs = BACKOFF_MIN_MS;
    this.draining = false;
    this.timer = null;
  }

  /**
   * Persist one message. Returns once it is genuinely on disk.
   *
   * Synchronous and fsynced on purpose. An async write that resolves before
   * the data reaches the platter would reintroduce exactly the loss window
   * this class exists to close, just a much narrower one.
   */
  enqueue(record) {
    const stamp = String(record.receivedAt).padStart(15, "0");
    const name = `${stamp}-${safeName(record.dedupeKey)}.json`;
    const finalPath = join(this.pendingDir, name);
    const tempPath = `${finalPath}.tmp`;

    const payload = JSON.stringify({ attempts: 0, ...record }, null, 2);
    const fd = openSync(tempPath, "w");
    try {
      writeSync(fd, payload);
      fsyncSync(fd); // the actual durability guarantee
    } finally {
      closeSync(fd);
    }
    renameSync(tempPath, finalPath); // atomic: readers never see a partial file
    return finalPath;
  }

  /** Messages waiting to be accepted by ARIA, oldest first. */
  pending() {
    return readdirSync(this.pendingDir)
      .filter((f) => f.endsWith(".json"))
      .sort();
  }

  counts() {
    return {
      pending: this.pending().length,
      dead: readdirSync(this.deadDir).filter((f) => f.endsWith(".json")).length,
    };
  }

  /**
   * Try to deliver everything pending.
   *
   * `deliver(record)` must resolve true only when ARIA has confirmed the
   * message is durable at its end. Any other outcome — network error, 5xx,
   * timeout — must be false, and the file stays put.
   *
   * Stops at the first failure rather than grinding through the whole backlog:
   * if one delivery failed because ARIA is down, the next will too, and
   * ordering is preserved by not skipping ahead.
   */
  async drain(deliver) {
    if (this.draining) return { delivered: 0, failed: 0 };
    this.draining = true;
    let delivered = 0;
    let failed = 0;

    try {
      for (const file of this.pending()) {
        const path = join(this.pendingDir, file);
        let record;
        try {
          record = JSON.parse(readFileSync(path, "utf8"));
        } catch (err) {
          // Unparseable file: park it rather than crash-looping on it.
          console.error(`[spool] unreadable ${file}, moving to dead/: ${err.message}`);
          renameSync(path, join(this.deadDir, file));
          continue;
        }

        let ok = false;
        try {
          ok = await deliver(record);
        } catch (err) {
          console.warn(`[spool] delivery threw for ${file}: ${err?.message || err}`);
        }

        if (ok) {
          unlinkSync(path); // acknowledged by ARIA — safe to forget
          delivered += 1;
          continue;
        }

        failed += 1;
        record.attempts = (record.attempts || 0) + 1;
        if (record.attempts >= MAX_ATTEMPTS) {
          writeFileSync(path, JSON.stringify(record, null, 2));
          renameSync(path, join(this.deadDir, file));
          console.error(
            `[spool] ${file} undeliverable after ${record.attempts} attempts — ` +
              `moved to dead/. It is NOT lost; inspect and replay it.`,
          );
          continue;
        }
        writeFileSync(path, JSON.stringify(record, null, 2));
        break; // ARIA is down; stop and let backoff handle the retry
      }
    } finally {
      this.draining = false;
    }

    // Successful delivery resets the backoff so recovery is immediate.
    this.backoffMs =
      failed > 0
        ? Math.min(this.backoffMs * 2, BACKOFF_MAX_MS)
        : BACKOFF_MIN_MS;

    return { delivered, failed };
  }

  /**
   * Keep draining forever, backing off while ARIA is unavailable.
   *
   * Called once at startup, which is what makes a backlog accumulated during
   * downtime flush automatically when the bridge or ARIA comes back.
   */
  startAutoDrain(deliver) {
    const tick = async () => {
      const { delivered, failed } = await this.drain(deliver);
      if (delivered > 0) {
        console.log(
          `[spool] delivered ${delivered} buffered message(s); ` +
            `${this.pending().length} still pending`,
        );
      }
      if (failed > 0) {
        console.warn(
          `[spool] ARIA unreachable — ${this.pending().length} message(s) held ` +
            `on disk, retrying in ${Math.round(this.backoffMs / 1000)}s`,
        );
      }
      this.timer = setTimeout(tick, this.backoffMs);
      this.timer.unref?.();
    };
    tick();
  }

  stop() {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
  }
}

/** Filesystem-safe fragment of a WhatsApp message id. */
function safeName(value) {
  return String(value || "unknown")
    .replace(/[^a-zA-Z0-9._-]/g, "_")
    .slice(0, 80);
}
