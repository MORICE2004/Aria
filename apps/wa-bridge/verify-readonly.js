/**
 * Send-capability containment check.
 *
 * The bridge's safety claim used to be "nothing here can send". Now that ARIA
 * can send when explicitly authorised, the claim is narrower and more precise:
 *
 *   • the OBSERVER (index.js and everything it imports) cannot send
 *   • sending exists in exactly ONE file, sender.js, which is a separate
 *     process with its own linked device
 *
 * Both halves are checked mechanically, because a safety property nobody
 * verifies is a safety property that quietly stops being true. Safety you can
 * grep for beats safety you have to trust.
 *
 * Run with: npm run verify-readonly
 * Exits non-zero if a sending API appears anywhere except sender.js, or if
 * sender.js has grown reasoning it should not have.
 */

import { readFileSync, readdirSync } from "node:fs";
import { dirname, extname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));

// Baileys' outbound surface.
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

// The one file allowed to send, and the only one.
const SENDER = "sender.js";

const SKIP_FILES = new Set(["verify-readonly.js"]); // this file names the APIs
const SKIP_DIRS = new Set(["node_modules", "auth", "auth-sender", "spool", ".git"]);

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

function codeLines(file) {
  // Comments may legitimately name these APIs while explaining the policy.
  return readFileSync(file, "utf8")
    .split("\n")
    .map((line, index) => ({ text: line, number: index + 1 }))
    .filter(({ text }) => {
      const trimmed = text.trim();
      return !trimmed.startsWith("*") && !trimmed.startsWith("//");
    });
}

let violations = 0;
let senderSends = false;

for (const file of sourceFiles(HERE)) {
  const name = relative(HERE, file);
  const isSender = name === SENDER;

  for (const { text, number } of codeLines(file)) {
    for (const api of FORBIDDEN) {
      if (!text.includes(api)) continue;

      if (isSender) {
        senderSends = true;
        continue; // this file is allowed to send; that is its whole job
      }
      console.error(`X ${name}:${number} uses send API "${api}" outside ${SENDER}`);
      console.error(`    ${text.trim()}`);
      violations++;
    }
  }
}

// The sender must stay dumb. If it grows decision-making, the separation
// between "the process that thinks" and "the process that sends" is gone, and
// with it the guarantee that neither can act alone.
const senderSource = readFileSync(join(HERE, SENDER), "utf8");
const REASONING_SMELLS = [
  "classifyMessage",
  "shouldReply",
  "generateReply",
  "decideWhether",
  "openai",
  "anthropic",
  "ollama",
];
for (const smell of REASONING_SMELLS) {
  if (senderSource.includes(smell)) {
    console.error(
      `X ${SENDER} contains "${smell}" — the sender must not decide anything.`,
    );
    violations++;
  }
}

if (violations > 0) {
  console.error(
    `\nX CONTAINMENT VIOLATED: ${violations} problem(s).\n` +
      `  Sending must exist only in ${SENDER}, and ${SENDER} must not reason.\n` +
      "  Route decisions through ARIA's autonomy engine and Action Gateway.\n",
  );
  process.exit(1);
}

console.log("+ observer is read-only: no send APIs outside sender.js");
console.log(
  senderSends
    ? "+ sender.js holds the only send capability, and contains no reasoning"
    : "+ no send capability present anywhere (sender.js is inert)",
);
