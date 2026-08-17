/**
 * Mirror a pairing QR to disk, for when the terminal one will not scan.
 *
 * Windows terminals draw each QR module as a half-block character, and the
 * console font's aspect ratio often squashes them just enough that a phone
 * camera refuses the code. That failure is indistinguishable from a broken
 * pairing flow, so there has to be a second way to get at the same code:
 * scripts/render-whatsapp-qr.py turns whichever file is live into a full-size
 * scannable page.
 *
 * Shared by both processes because both pair as their own device — the observer
 * and the sender each need this, and a copy in each file would be a copy to fix
 * twice. It writes one local file and prints two lines; it holds no WhatsApp
 * capability of its own, so the read-only guarantee on the observer is
 * untouched.
 *
 * The payload IS a credential while it lives: anyone who scans it links a
 * device to the account. WhatsApp rotates it about every 20 seconds, the file is
 * overwritten each time, and it is deleted the moment the device connects. Both
 * filenames are gitignored.
 */

import { existsSync, rmSync, writeFileSync } from "node:fs";
import { basename, join, resolve } from "node:path";

/**
 * @param {string} dir   the bridge directory (where the file is written)
 * @param {string} role  "observer" | "sender" — one file each, so linking one
 *                       device does not overwrite the other's live code
 */
export function makeQrFallback(dir, role) {
  const file = join(dir, `qr-current-${role}.txt`);
  const repo = resolve(dir, "..", "..");

  return {
    file,

    /** Called for every new code WhatsApp issues. */
    write(qr) {
      try {
        writeFileSync(file, qr, "utf8");
        // Absolute paths: the reader is in whatever directory they happen to be
        // in, and PowerShell will not run a relative executable path at all.
        console.log("\n  Cannot scan the code above? In a SECOND terminal, run:");
        console.log(
          `    ${join(repo, "apps", "api", ".venv", "Scripts", "python.exe")} ` +
            `${join(repo, "scripts", "render-whatsapp-qr.py")} --role ${role}`,
        );
        console.log(
          "  It opens a full-size, scannable page and follows this code as it" +
            " rotates.\n",
        );
      } catch (err) {
        console.warn(`  could not write ${basename(file)}: ${err?.message}`);
      }
    },

    /** Called on connect: the code is spent, and leaving it invites a stale scan. */
    clear() {
      try {
        if (existsSync(file)) rmSync(file);
      } catch {
        /* a leftover file is harmless: the code in it expired seconds later */
      }
    },
  };
}
