/**
 * Read-only enforcement check.
 *
 * The bridge's safety claim is "this code cannot send". That claim is worth
 * nothing if a future edit quietly adds a send call, so it is checked
 * mechanically instead of trusted.
 *
 * Run with: npm run verify-readonly
 * Exits non-zero if any WhatsApp-sending API appears in the bridge source.
 */

import { readFileSync, readdirSync } from "node:fs";
import { dirname, extname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));

// Baileys' outbound surface. If any of these appear, the bridge is no longer
// read-only and the check must fail loudly.
const FORBIDDEN = [
  "sendMessage",
  "sendPresenceUpdate",
  "readMessages",
  "sendReceipt",
  "sendReadReceipt",
  "chatModify",
  "updateProfileStatus",
  "updateProfileName",
  "groupCreate",
  "groupParticipantsUpdate",
  "sendMessageAck",
  "relayMessage",
];

const SKIP_FILES = new Set(["verify-readonly.js"]); // this file names them
const SKIP_DIRS = new Set(["node_modules", "auth", ".git"]);

function sourceFiles(dir) {
  const out = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      if (!SKIP_DIRS.has(entry.name)) out.push(...sourceFiles(join(dir, entry.name)));
    } else if ([".js", ".mjs", ".ts"].includes(extname(entry.name))) {
      if (!SKIP_FILES.has(entry.name)) out.push(join(dir, entry.name));
    }
  }
  return out;
}

let violations = 0;
for (const file of sourceFiles(HERE)) {
  const lines = readFileSync(file, "utf8").split("\n");
  lines.forEach((line, i) => {
    // Ignore comment lines: prose may legitimately mention the API names.
    const trimmed = line.trim();
    if (trimmed.startsWith("*") || trimmed.startsWith("//")) return;

    for (const api of FORBIDDEN) {
      if (line.includes(api)) {
        console.error(`✗ ${file}:${i + 1} uses forbidden send API "${api}"`);
        console.error(`    ${trimmed}`);
        violations++;
      }
    }
  });
}

if (violations > 0) {
  console.error(
    `\n✗ READ-ONLY VIOLATED: ${violations} sending call(s) found.\n` +
      "  The ARIA bridge must never be able to send. Remove them, or route\n" +
      "  the action through ARIA's Action Gateway instead.\n",
  );
  process.exit(1);
}

console.log("✓ read-only verified: no WhatsApp sending APIs in the bridge source");
