/**
 * Delivery to ARIA's ingest endpoint.
 *
 * Extracted from index.js so the live outage check can exercise the exact
 * same delivery code the bridge runs. A recovery test against a reimplemented
 * client proves nothing about the client that actually handles your messages.
 */

const POST_TIMEOUT_MS = 20000;

/**
 * Build a deliver function for the spool.
 *
 * The returned function resolves TRUE only when ARIA has confirmed the
 * message is durable at its end (`queued: true`). Everything else —
 * connection refused, timeout, 5xx, an unexpected body — resolves false, and
 * the spool keeps the message and retries.
 *
 * This strictness is the contract that makes the spool correct: when in doubt,
 * we have NOT delivered. A 4xx is retried rather than discarded, because the
 * 4xx we can realistically hit is a 401 from a secret mismatch — a
 * misconfiguration to fix, not a reason to throw away someone's message.
 */
export function makeDeliver(cfg, { log = console } = {}) {
  return async function deliverToAria(record) {
    const { handle, name, body, direction, dedupeKey, timestamp } = record;
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
          name,
          body,
          direction,
          message_id: dedupeKey,
          timestamp,
        }),
        signal: controller.signal,
      });

      if (!res.ok) {
        log.warn(
          `[bridge] ARIA returned ${res.status} — message HELD on disk, will retry`,
        );
        return false;
      }

      const data = await res.json().catch(() => ({}));
      if (data.queued !== true) {
        log.warn("[bridge] ARIA did not confirm durability — holding message");
        return false;
      }

      const mode = data.observation?.effective_mode;
      log.log(
        `[bridge] -> ARIA  ${direction}  ${name || handle}: ` +
          `"${body.slice(0, 50)}${body.length > 50 ? "..." : ""}"` +
          (data.duplicate ? "  [duplicate, already known]" : "") +
          (mode ? `  [${mode}]` : ""),
      );
      return true;
    } catch (err) {
      log.warn(`[bridge] forward failed: ${err?.message || err}`);
      return false;
    } finally {
      clearTimeout(timer);
    }
  };
}
