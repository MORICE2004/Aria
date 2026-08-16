/**
 * Spool durability tests.
 *
 * Run with: npm test
 *
 * The scenario every one of these encodes: WhatsApp has already delivered the
 * message. Nothing will ever redeliver it. If the bridge loses it here, it is
 * gone permanently. So "ARIA was down" must never mean "the message is gone".
 */

import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, beforeEach, describe, test } from "node:test";

import { Spool } from "./spool.js";

let root;
const roots = [];

beforeEach(() => {
  root = mkdtempSync(join(tmpdir(), "aria-spool-"));
  roots.push(root);
});

after(() => {
  for (const dir of roots) rmSync(dir, { recursive: true, force: true });
});

function message(overrides = {}) {
  return {
    dedupeKey: "wamid.ABC123",
    handle: "friend@s.whatsapp.net",
    name: "Friend",
    body: "you around?",
    direction: "in",
    timestamp: 1_700_000_000,
    receivedAt: Date.now(),
    ...overrides,
  };
}

describe("spool", () => {
  test("a message is on disk before any delivery is attempted", () => {
    const spool = new Spool(root);
    spool.enqueue(message());
    assert.equal(spool.counts().pending, 1);
  });

  test("ARIA being unavailable holds the message instead of dropping it", async () => {
    const spool = new Spool(root);
    spool.enqueue(message());

    // The old bug, reproduced exactly: the POST fails.
    const deadApi = async () => {
      throw new Error("connect ECONNREFUSED 127.0.0.1:8000");
    };

    const result = await spool.drain(deadApi);
    assert.equal(result.delivered, 0);
    assert.equal(result.failed, 1);
    // THE ASSERTION THAT MATTERS: the message still exists.
    assert.equal(spool.counts().pending, 1);
  });

  test("the held message is delivered once ARIA comes back", async () => {
    const spool = new Spool(root);
    spool.enqueue(message());

    await spool.drain(async () => false); // ARIA down
    assert.equal(spool.counts().pending, 1);

    const seen = [];
    await spool.drain(async (record) => {
      seen.push(record.body);
      return true; // ARIA back up and confirming durability
    });

    assert.deepEqual(seen, ["you around?"]);
    assert.equal(spool.counts().pending, 0); // acknowledged, so forgotten
  });

  test("a backlog survives a bridge restart and replays in order", async () => {
    const first = new Spool(root);
    first.enqueue(message({ dedupeKey: "m1", body: "one", receivedAt: 1000 }));
    first.enqueue(message({ dedupeKey: "m2", body: "two", receivedAt: 2000 }));
    first.enqueue(message({ dedupeKey: "m3", body: "three", receivedAt: 3000 }));
    await first.drain(async () => false); // ARIA down throughout
    first.stop();

    // Bridge process dies and restarts against the same directory.
    const restarted = new Spool(root);
    assert.equal(restarted.counts().pending, 3);

    const seen = [];
    await restarted.drain(async (record) => {
      seen.push(record.body);
      return true;
    });

    // Order preserved: a conversation replayed out of order is worse than late.
    assert.deepEqual(seen, ["one", "two", "three"]);
    assert.equal(restarted.counts().pending, 0);
  });

  test("delivery stops at the first failure so ordering is not broken", async () => {
    const spool = new Spool(root);
    spool.enqueue(message({ dedupeKey: "m1", body: "one", receivedAt: 1000 }));
    spool.enqueue(message({ dedupeKey: "m2", body: "two", receivedAt: 2000 }));

    const seen = [];
    await spool.drain(async (record) => {
      seen.push(record.body);
      return false; // ARIA rejecting everything
    });

    // Only the first was attempted; "two" was not skipped ahead of "one".
    assert.deepEqual(seen, ["one"]);
    assert.equal(spool.counts().pending, 2);
  });

  test("a non-durable response (queued != true) is treated as failure", async () => {
    // Guards the contract between bridge and API: only an explicit durability
    // promise may delete the local copy.
    const spool = new Spool(root);
    spool.enqueue(message());
    await spool.drain(async () => false);
    assert.equal(spool.counts().pending, 1);
  });

  test("attempt counts persist across restarts", async () => {
    const spool = new Spool(root);
    spool.enqueue(message());
    await spool.drain(async () => false);

    const reopened = new Spool(root);
    await reopened.drain(async () => false);

    const file = readdirSync(join(root, "pending"))[0];
    const record = JSON.parse(readFileSync(join(root, "pending", file), "utf8"));
    assert.equal(record.attempts, 2);
  });

  test("an undeliverable message ends in dead/, never deleted", async () => {
    const spool = new Spool(root);
    spool.enqueue(message());

    // Hammer it past MAX_ATTEMPTS.
    for (let i = 0; i < 25; i++) await spool.drain(async () => false);

    const counts = spool.counts();
    assert.equal(counts.pending, 0);
    assert.equal(counts.dead, 1); // parked and inspectable, not lost
  });

  test("an unreadable spool file is quarantined, not crash-looped", async () => {
    const spool = new Spool(root);
    writeFileSync(join(root, "pending", "000-corrupt.json"), "{ this is not json");

    await spool.drain(async () => true);

    assert.equal(spool.counts().pending, 0);
    assert.equal(spool.counts().dead, 1);
  });

  test("backoff grows while down and resets on recovery", async () => {
    const spool = new Spool(root);
    spool.enqueue(message({ dedupeKey: "m1", receivedAt: 1000 }));

    await spool.drain(async () => false);
    const afterFirstFailure = spool.backoffMs;
    await spool.drain(async () => false);
    assert.ok(spool.backoffMs > afterFirstFailure, "backoff should grow");

    await spool.drain(async () => true);
    assert.ok(
      spool.backoffMs < afterFirstFailure * 2,
      "backoff should reset after a successful delivery",
    );
  });
});
