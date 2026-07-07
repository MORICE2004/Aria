/**
 * Login page. Only relevant when ARIA_PASSWORD is set in the API's .env;
 * otherwise auth is disabled and this page says so.
 */
"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export default function LoginPage() {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.authStatus().then((s) => setEnabled(s.auth_enabled)).catch(() => setEnabled(null));
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const { token } = await api.login(password);
      localStorage.setItem("aria_token", token);
      window.location.href = "/";
    } catch {
      setError("Login failed — check your password.");
    }
  }

  return (
    <div className="mx-auto mt-24 max-w-sm rounded-lg border border-zinc-800 bg-zinc-900 p-6">
      <h2 className="mb-4 text-xl font-semibold">Unlock ARIA</h2>
      {enabled === false && (
        <p className="text-sm text-zinc-400">
          Auth is currently disabled (no ARIA_PASSWORD set) — you can use ARIA
          without logging in.
        </p>
      )}
      {enabled !== false && (
        <form onSubmit={submit} className="space-y-3">
          <label htmlFor="password" className="block text-sm text-zinc-400">
            Password
          </label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoFocus
            className="w-full rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm outline-none focus:border-zinc-500"
          />
          {error && (
            <p role="alert" className="text-xs text-red-400">
              {error}
            </p>
          )}
          <button className="w-full rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500">
            Log in
          </button>
        </form>
      )}
    </div>
  );
}
