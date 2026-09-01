/**
 * Frontend test configuration.
 *
 * Vitest rather than Jest because the app is already built by a Vite-family
 * toolchain; there is no second transform pipeline to keep in step with the
 * Next.js one, and TypeScript and the `@/` alias work without configuration.
 *
 * jsdom because the things worth testing here are browser behaviours: whether
 * a request carries the auth token, whether a 401 sends him to the login page,
 * whether a component renders "queued" as queued rather than as sent.
 */
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": resolve(import.meta.dirname, "src") },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}"],
  },
});
