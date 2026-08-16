/**
 * Persistent warning when ARIA has no password.
 *
 * An unprotected ARIA must not look identical to a protected one. She listens
 * on the LAN so the phone can reach her, so "no password" means anyone on the
 * network can read her memory and change her autonomy settings.
 *
 * Deliberately not dismissible. A banner you can dismiss is a banner you stop
 * seeing, and this one describes a condition that does not go away on its own.
 */
"use client";

import { useEffect, useState } from "react";
import { ShieldAlert } from "lucide-react";

import { API_URL } from "@/lib/api";

export function SecurityBanner() {
  const [warning, setWarning] = useState("");

  useEffect(() => {
    // Uses fetch directly rather than the api client: /auth/status is public,
    // and this must render even when nothing else can authenticate.
    const check = () =>
      fetch(`${API_URL}/auth/status`)
        .then((r) => r.json())
        .then((d) => setWarning(d.auth_enabled ? "" : (d.warning ?? "")))
        .catch(() => setWarning("")); // API down is a different problem
    const timer = setTimeout(check, 0);
    return () => clearTimeout(timer);
  }, []);

  if (!warning) return null;

  return (
    <div
      role="alert"
      className="flex items-start gap-3 border-b border-amber-500/30 bg-amber-500/10 px-4 py-2 text-xs text-amber-200"
    >
      <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <p>
        {warning}{" "}
        <span className="text-amber-300/80">
          ARIA will draft messages but refuses to send any on her own until a
          password is set.
        </span>
      </p>
    </div>
  );
}
