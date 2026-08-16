/**
 * Connect your phone — scan and go.
 *
 * The address of this PC changes whenever the router reassigns it, so the QR
 * is generated fresh from the API on every load rather than being written
 * down anywhere.
 */
"use client";

import { useEffect, useState } from "react";
import { API_URL } from "@/lib/api";

type Info = { lan_ip: string | null; phone_url: string | null; reason?: string | null };

export default function ConnectPage() {
  const [info, setInfo] = useState<Info | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    fetch(`${API_URL}/connect`)
      .then((r) => r.json())
      .then(setInfo)
      .catch(() => setInfo({ lan_ip: null, phone_url: null, reason: "API unreachable" }));
  }, []);

  return (
    <div className="mx-auto max-w-xl">
      <h2 className="mb-1 text-2xl font-semibold">Open ARIA on your phone</h2>
      <p className="mb-6 text-sm text-zinc-400">
        Point your phone&apos;s camera at the code. Your phone must be on the
        same Wi-Fi as this PC.
      </p>

      {info?.phone_url ? (
        <div className="glass rounded-xl p-6 text-center">
          {/* White plate: QR codes need light background to scan reliably. */}
          <div className="mx-auto mb-5 w-fit rounded-xl bg-white p-4">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={`${API_URL}/connect/qr`}
              alt={`QR code linking to ${info.phone_url}`}
              width={240}
              height={240}
              className="block h-60 w-60"
            />
          </div>

          <p className="mb-1 font-mono text-lg text-cyan-300">{info.phone_url}</p>
          <button
            onClick={async () => {
              await navigator.clipboard.writeText(info.phone_url!);
              setCopied(true);
              setTimeout(() => setCopied(false), 1500);
            }}
            className="rounded-md border border-zinc-700 px-3 py-1 text-xs text-zinc-300 hover:text-white"
          >
            {copied ? "Copied ✓" : "Copy link"}
          </button>

          <ol className="mx-auto mt-6 max-w-sm space-y-2 text-left text-sm text-zinc-400">
            <li>
              <strong className="text-zinc-200">1.</strong> Scan the code, or
              type that address into your phone&apos;s browser.
            </li>
            <li>
              <strong className="text-zinc-200">2.</strong> In the browser menu,
              tap <em>Add to Home Screen</em> — ARIA gets its own icon and opens
              full-screen, like an app.
            </li>
            <li>
              <strong className="text-zinc-200">3.</strong> Can&apos;t connect?
              Run{" "}
              <code className="rounded bg-white/5 px-1.5 py-0.5 text-xs">
                allow-phone.ps1
              </code>{" "}
              once as Administrator to open the firewall.
            </li>
          </ol>
        </div>
      ) : (
        <div className="glass rounded-xl p-6">
          <p className="text-sm text-amber-300">
            {info?.reason ?? "Finding this PC's network address…"}
          </p>
          <p className="mt-2 text-xs text-zinc-500">
            ARIA needs this PC to be on Wi-Fi (or ethernet) to be reachable
            from your phone.
          </p>
        </div>
      )}
    </div>
  );
}
